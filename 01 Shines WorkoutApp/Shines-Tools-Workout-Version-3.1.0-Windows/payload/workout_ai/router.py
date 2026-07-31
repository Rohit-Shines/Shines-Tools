from __future__ import annotations

from dataclasses import dataclass

from .classifier import Classification
from .exercises import TrackerOutput


@dataclass
class RouteDecision:
    active_exercise: str | None
    candidate_exercise: str | None
    candidate_confidence: float
    switched: bool = False


class AutoExerciseRouter:
    """Accuracy-first router for automatic and limited-exercise workouts.

    Every enabled tracker runs from frame one. A unique high-quality completed
    movement can therefore be counted immediately, even before the temporal
    classifier has fully named the exercise. This prevents losing the first
    several repetitions while retaining protection against shadow trackers.
    """

    def __init__(self) -> None:
        self.active: str | None = None
        self.last_active_evidence = -999.0
        self.pending_candidate: str | None = None
        self.pending_since = 0.0

    def reset(self) -> None:
        self.active = None
        self.last_active_evidence = -999.0
        self.pending_candidate = None
        self.pending_since = 0.0

    @staticmethod
    def _phase_bonus(output: TrackerOutput) -> float:
        if not output.valid_pose:
            return 0.0
        if output.rep_completed:
            return 0.46
        if output.phase not in ("search", "neutral", "position"):
            return 0.22
        return 0.08

    def evidence_scores(
        self,
        classification: Classification,
        outputs: dict[str, TrackerOutput],
        preferred_exercise: str | None = None,
    ) -> dict[str, float]:
        result: dict[str, float] = {}
        for exercise, output in outputs.items():
            classifier_score = classification.scores.get(exercise, 0.0)
            tracker_score = output.confidence if output.valid_pose else 0.0
            preference_bonus = 0.20 if preferred_exercise == exercise else 0.0
            result[exercise] = (
                0.48 * classifier_score
                + 0.34 * tracker_score
                + self._phase_bonus(output)
                + preference_bonus
            )
        return result

    def update(
        self,
        timestamp: float,
        classification: Classification,
        outputs: dict[str, TrackerOutput],
        preferred_exercise: str | None = None,
    ) -> RouteDecision:
        scores = self.evidence_scores(classification, outputs, preferred_exercise)
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        candidate, confidence = ordered[0] if ordered else (None, 0.0)
        second = ordered[1][1] if len(ordered) > 1 else 0.0
        margin = confidence - second
        switched = False

        if self.active is not None and self.active in outputs:
            active_output = outputs[self.active]
            active_score = scores.get(self.active, 0.0)
            if active_output.valid_pose and (
                active_output.phase not in ("search", "neutral", "position")
                or active_score >= 0.42
                or classification.candidate == self.active
            ):
                self.last_active_evidence = timestamp

            # Release an exercise quickly once its posture disappears, allowing
            # the next exercise's very first completed repetition to switch in.
            if timestamp - self.last_active_evidence > 1.35:
                self.active = None
                self.pending_candidate = None

        if classification.stable and classification.exercise is not None:
            candidate = classification.exercise
            confidence = scores.get(candidate, classification.confidence)

        candidate_ok = candidate is not None and confidence >= 0.40 and margin >= 0.018
        if self.active is None and candidate_ok:
            if self.pending_candidate == candidate:
                if timestamp - self.pending_since >= 0.12:
                    self.active = candidate
                    self.last_active_evidence = timestamp
                    self.pending_candidate = None
                    switched = True
            else:
                self.pending_candidate = candidate
                self.pending_since = timestamp
        elif self.active is not None and candidate_ok and candidate != self.active:
            active_score = scores.get(self.active, 0.0)
            active_valid = outputs.get(self.active).valid_pose if self.active in outputs else False
            needed_advantage = 0.07 if not active_valid else 0.12
            if confidence >= active_score + needed_advantage:
                if self.pending_candidate == candidate:
                    if timestamp - self.pending_since >= (0.20 if not active_valid else 0.42):
                        self.active = candidate
                        self.last_active_evidence = timestamp
                        self.pending_candidate = None
                        switched = True
                else:
                    self.pending_candidate = candidate
                    self.pending_since = timestamp
            else:
                self.pending_candidate = None
        else:
            self.pending_candidate = None

        return RouteDecision(self.active, candidate, float(confidence), switched)

    def accept_completed_rep(
        self,
        exercise: str,
        timestamp: float,
        classification: Classification,
        outputs: dict[str, TrackerOutput],
        preferred_exercise: str | None = None,
    ) -> bool:
        output = outputs[exercise]
        if not output.rep_completed or not output.valid_pose:
            return False

        scores = self.evidence_scores(classification, outputs, preferred_exercise)
        completed_now = [name for name, value in outputs.items() if value.rep_completed and value.valid_pose]
        classifier_score = classification.scores.get(exercise, 0.0)

        # High-risk confusion pairs require explicit classifier separation.
        # This prevents a shoulder press from being saved as a curl and a
        # horizontal push-up from being displayed/saved as a squat.
        conflict_map = {
            "pushup": "squat",
            "squat": "pushup",
            "curl": "shoulder_press",
            "shoulder_press": "curl",
        }
        competitor = conflict_map.get(exercise)
        if competitor in outputs:
            competitor_score = classification.scores.get(competitor, 0.0)
            classifier_agrees_now = classification.exercise == exercise or classification.candidate == exercise
            if not classifier_agrees_now and classifier_score < competitor_score + 0.055:
                return False
        best_name = max(scores, key=scores.get) if scores else None
        best_score = scores.get(best_name, 0.0) if best_name else 0.0
        exercise_score = scores.get(exercise, 0.0)
        quality = output.rep_quality if output.rep_quality is not None else output.form_score / 100.0
        strong_tracker = output.confidence >= 0.44 and quality >= output.quality_threshold * 0.80

        if self.active == exercise:
            self.last_active_evidence = timestamp
            return True

        # A hands-free user hint never disables automatic recognition; it only
        # lowers the ambiguity threshold for the selected enabled exercise.
        if preferred_exercise == exercise and strong_tracker:
            if len(completed_now) == 1 or exercise_score >= best_score - 0.08:
                self.active = exercise
                self.last_active_evidence = timestamp
                self.pending_candidate = None
                return True

        # Fast-start rule: a unique, posture-gated, good-quality completion is
        # counted immediately. This is what preserves count 1 rather than waiting
        # until count 3 or 4 for exercise recognition.
        classifier_agrees = classification.candidate == exercise or classification.exercise == exercise
        strongest_classifier = bool(classification.scores) and max(
            classification.scores, key=classification.scores.get
        ) == exercise
        distinctive_fast = exercise in {
            "pushup", "plank", "situp", "squat_hold", "overhead_stretch",
            "forward_fold", "taekwondo_kick", "head_turn", "arm_circle", "hip_circle",
        }
        if (
            self.active is None
            and len(completed_now) == 1
            and strong_tracker
            and (classifier_agrees or strongest_classifier or distinctive_fast)
        ):
            self.active = exercise
            self.last_active_evidence = timestamp
            self.pending_candidate = None
            return True

        if self.active is not None and self.active != exercise:
            active_output = outputs.get(self.active)
            active_valid = bool(active_output and active_output.valid_pose)
            strong_switch = (
                classification.stable
                and classification.exercise == exercise
                and classification.margin >= 0.055
            )
            # If the previous exercise's posture is gone and only one tracker
            # completed, switch immediately rather than discarding the first rep.
            if not active_valid and len(completed_now) == 1 and strong_tracker:
                self.active = exercise
                self.last_active_evidence = timestamp
                self.pending_candidate = None
                return True
            if timestamp - self.last_active_evidence < 0.95 and not strong_switch:
                return False

        distinctive = exercise in {
            "pushup",
            "situp",
            "plank",
            "squat_hold",
            "overhead_stretch",
            "forward_fold",
            "taekwondo_kick",
            "head_turn",
            "arm_circle",
            "hip_circle",
        }
        strongest = best_name == exercise and exercise_score >= 0.44
        close_to_best = exercise_score >= best_score - 0.035 and classifier_score >= 0.30
        accepted = (distinctive and strong_tracker) or classifier_agrees or strongest or close_to_best
        if accepted:
            self.active = exercise
            self.last_active_evidence = timestamp
            self.pending_candidate = None
        return accepted
