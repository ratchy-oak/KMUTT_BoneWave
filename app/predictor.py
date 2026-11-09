"""Three-class prediction against the recorded real dataset."""
from hashlib import sha256
from pathlib import Path

import numpy as np

from .touchstone import load_standard_trace

ROOT = Path(__file__).resolve().parents[1]
WARNING = "Research prototype — Not for medical diagnosis"
CLASS_KEYS = ("air", "normal", "crack")
CLASS_LABELS = {
    "air": "AIR",
    "normal": "NOT_FRACTURED",
    "crack": "FRACTURED",
}
PROBABILITY_TEMPERATURE = 0.5
MIN_CLASS_PROBABILITY = 0.55
MIN_CLASS_MARGIN = 0.15
MAX_NORMALIZED_DISTANCE = 1.5


class Predictor:
    def __init__(self):
        self.reference_dir = ROOT / "data" / "real"
        self.reference_bank = {kind: [] for kind in CLASS_KEYS}
        self.reference_files = {kind: [] for kind in CLASS_KEYS}
        self.reference_duplicates = {kind: [] for kind in CLASS_KEYS}
        self.reference_errors = []
        self._load_real_reference_bank()
        if any(not len(self.reference_bank[kind]) for kind in CLASS_KEYS):
            raise RuntimeError(
                "data/real must contain readable air, normal, and crack .s2p references"
            )
        self.reference_radius = {
            kind: self._bank_radius(self.reference_bank[kind]) for kind in CLASS_KEYS
        }

    def _load_real_reference_bank(self):
        """Load unique real sweeps captured at multiple angles."""
        for kind in CLASS_KEYS:
            seen = {}
            folder = self.reference_dir / kind
            for path in sorted(folder.glob("*.s2p")) if folder.exists() else []:
                digest = sha256(path.read_bytes()).hexdigest()
                if digest in seen:
                    self.reference_duplicates[kind].append(
                        {"file": path.name, "duplicate_of": seen[digest]}
                    )
                    continue
                try:
                    trace = load_standard_trace(path)
                except Exception as exc:
                    self.reference_errors.append({"file": str(path), "error": str(exc)})
                    continue
                seen[digest] = path.name
                self.reference_files[kind].append(path.name)
                self.reference_bank[kind].append(self._smooth_magnitude(trace))
            self.reference_bank[kind] = (
                np.stack(self.reference_bank[kind])
                if self.reference_bank[kind]
                else np.empty((0, 0), dtype=float)
            )

    @staticmethod
    def _smooth_magnitude(trace):
        return np.convolve(trace.s21_db, np.ones(7) / 7, mode="same")[3:-3]

    @staticmethod
    def _bank_distance(sample, bank, k=5):
        if len(bank) == 0:
            return float("inf")
        distances = np.sqrt(np.mean((bank - sample) ** 2, axis=1))
        count = min(k, len(distances))
        return float(np.mean(np.partition(distances, count - 1)[:count]))

    @classmethod
    def _bank_radius(cls, bank, k=5):
        if len(bank) < 2:
            return float("inf")
        distances = [
            cls._bank_distance(sample, np.delete(bank, index, axis=0), k)
            for index, sample in enumerate(bank)
        ]
        return max(0.25, float(np.percentile(distances, 95)))

    def reference_status(self):
        real_counts = {kind: len(bank) for kind, bank in self.reference_bank.items()}
        return {
            "ready": True,
            "source": "real_multi_angle_dataset",
            "classes": [CLASS_LABELS[kind] for kind in CLASS_KEYS],
            "reference_counts": real_counts,
            "ignored_exact_duplicates": sum(
                len(items) for items in self.reference_duplicates.values()
            ),
            "load_errors": len(self.reference_errors),
        }

    @staticmethod
    def _probabilities(values, temperature):
        shifted = values - np.min(values)
        weights = np.exp(-shifted / max(temperature, 1e-9))
        return weights / np.sum(weights)

    def _result(
        self,
        distances,
        decision_values,
        probabilities,
        outlier,
        model_mode,
        reference_domain,
        reference_counts,
        validation_scope,
        separation_warning=False,
        allow_uncertain=True,
    ):
        order = np.argsort(probabilities)[::-1]
        winner_index, runner_up_index = int(order[0]), int(order[1])
        winner_kind = CLASS_KEYS[winner_index]
        winner_probability = float(probabilities[winner_index])
        margin = float(probabilities[winner_index] - probabilities[runner_up_index])
        ambiguous = bool(
            allow_uncertain
            and (
                separation_warning
                or winner_probability < MIN_CLASS_PROBABILITY
                or margin < MIN_CLASS_MARGIN
            )
        )
        label = (
            "UNCERTAIN"
            if allow_uncertain and (outlier or ambiguous)
            else CLASS_LABELS[winner_kind]
        )
        class_probabilities = {
            CLASS_LABELS[kind]: float(probabilities[index])
            for index, kind in enumerate(CLASS_KEYS)
        }
        return {
            "predicted_class": label,
            "prediction": label,
            "fracture_probability": class_probabilities["FRACTURED"],
            "confidence": winner_probability,
            "class_probabilities": class_probabilities,
            "similarity_air": float(np.exp(-decision_values[0])),
            "similarity_normal": float(np.exp(-decision_values[1])),
            "similarity_crack": float(np.exp(-decision_values[2])),
            "model_mode": model_mode,
            "reference_domain": reference_domain,
            "distance_air_db": distances["air"],
            "distance_normal_db": distances["normal"],
            "distance_crack_db": distances["crack"],
            "out_of_distribution": bool(outlier),
            "ambiguous": ambiguous,
            "winning_margin": margin,
            "ood_score": float(decision_values[winner_index]),
            "reference_counts": reference_counts,
            "validation_scope": validation_scope,
            "warning": WARNING,
        }

    def _predict_real(self, sample):
        distances = {
            kind: self._bank_distance(sample, self.reference_bank[kind])
            for kind in CLASS_KEYS
        }
        normalized = np.asarray(
            [
                distances[kind] / (self.reference_radius[kind] + 1e-9)
                for kind in CLASS_KEYS
            ]
        )
        probabilities = self._probabilities(normalized, PROBABILITY_TEMPERATURE)
        winner_index = int(np.argmax(probabilities))
        outlier = bool(normalized[winner_index] > MAX_NORMALIZED_DISTANCE)
        return self._result(
            distances,
            normalized,
            probabilities,
            outlier,
            "real_three_class_reference_bank",
            "real_same_specimen_multi_angle",
            {kind: len(bank) for kind, bank in self.reference_bank.items()},
            "Same-specimen, multi-angle reference matching only",
        )

    def predict(self, trace):
        return self._predict_real(self._smooth_magnitude(trace))
