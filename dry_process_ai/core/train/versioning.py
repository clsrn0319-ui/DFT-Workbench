"""FT-08 — 모델 버전 관리 · 재학습 트리거.

모델 버전마다 학습 Lot 수, 하이퍼파라미터, seed, 데이터 출처 구성비를 기록한다.
모델 파일과 scaling registry 는 항상 1:1 짝으로 저장·로드하며,
로드 시 버전 일치를 검증한다 (규칙 R8, 리스크 R-03).
"""

from __future__ import annotations

import joblib
import tensorflow as tf
from sqlalchemy.orm import Session

from dry_process_ai.config import MODELS_DIR
from dry_process_ai.core.model.builder import ModelSpec, build_model
from dry_process_ai.core.train.trainer import TrainingResult
from dry_process_ai.data_access.db import ModelVersion
from dry_process_ai.data_access.preprocess import RegistryVersionMismatch, ScalingRegistry


def next_version(session: Session, structural_change: bool = False) -> str:
    """v{major}.{minor} — major: 구조 변경, minor: 재학습."""
    rows = [v.version_id for v in session.query(ModelVersion).all()]
    if not rows:
        return "v1.0"
    majors_minors = []
    for v in rows:
        try:
            major, minor = v.lstrip("v").split(".")
            majors_minors.append((int(major), int(minor)))
        except ValueError:
            continue
    major, minor = max(majors_minors) if majors_minors else (1, -1)
    return f"v{major + 1}.0" if structural_change else f"v{major}.{minor + 1}"


def save_model_version(
    session: Session,
    result: TrainingResult,
    version_id: str,
    dataset_tag: str | None = None,
    models_dir=MODELS_DIR,
) -> str:
    """모델 가중치 + ModelSpec + registry 를 한 디렉터리에 짝으로 저장한다."""
    if result.registry.version != version_id:
        # registry 버전을 모델 버전과 1:1 로 정렬한다
        result.registry.version = version_id
    model_dir = models_dir / f"dry_process_master_model_{version_id}"
    model_dir.mkdir(parents=True, exist_ok=True)

    result.model.save_weights(str(model_dir / "weights.h5"))
    joblib.dump(result.spec, model_dir / "model_spec.pkl")
    joblib.dump(result.registry, model_dir / "scaling_registry.pkl")

    session.merge(ModelVersion(
        version_id=version_id,
        train_lot_count=result.train_lot_count,
        measured_ratio=result.measured_ratio,
        hyperparameters=result.hyperparameters_json(),
        seed=result.spec.seed,
        registry_version=result.registry.version,
        dataset_tag=dataset_tag,
        pseudo_label_pass_rate=(
            result.pseudo_label_result.pass_rate if result.pseudo_label_result else None
        ),
    ))
    session.commit()
    return str(model_dir)


def load_model_version(version_id: str, models_dir=MODELS_DIR) -> tuple[tf.keras.Model, ModelSpec, ScalingRegistry]:
    """저장된 모델·registry 짝을 로드하고 버전 일치를 검증한다."""
    model_dir = models_dir / f"dry_process_master_model_{version_id}"
    spec: ModelSpec = joblib.load(model_dir / "model_spec.pkl")
    registry: ScalingRegistry = joblib.load(model_dir / "scaling_registry.pkl")
    if registry.version != version_id:
        raise RegistryVersionMismatch(
            f"registry 버전 {registry.version} ≠ 모델 버전 {version_id} — 역스케일링 불가 (규칙 R8)"
        )
    model = build_model(spec)
    model.load_weights(str(model_dir / "weights.h5"))
    return model, spec, registry


def should_retrain(session: Session, current_train_lot_count: int, new_lot_count: int) -> bool:
    """신규 실측 Lot 등록 시 재학습 트리거 (FT-08, FR-06)."""
    return new_lot_count > current_train_lot_count
