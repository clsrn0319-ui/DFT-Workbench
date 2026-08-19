"""SQLite 스키마 정의 (기능정의서 12.1).

stage_measure / process_condition 은 세로(long) 구조를 유지한다 —
압연 단수가 늘어나도 스키마 변경이 없게 하고, Lot 1건당 8개 관측치를
학습 신호로 쓰는 설계와 직결된다 (CLAUDE.md 7장).

electrode_porosity 는 예측·제약·알람 어디에도 사용하지 않지만 (규칙 R2)
향후 실측 체계 확보를 대비해 스키마에 자리만 남겨 둔다.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from dry_process_ai.config import DB_URL

Base = declarative_base()

SOURCE_MEASURED = "measured"
SOURCE_GENERATED = "generated"


class Lot(Base):
    """실험 Lot 마스터. 전극 면적은 학습 입력이 아닌 Lot 속성 (규칙 R4)."""

    __tablename__ = "lot"

    lot_id = Column(String, primary_key=True)
    experiment_date = Column(String)
    operator = Column(String)
    electrode_area_cm2 = Column(Float)  # Lot 마다 가변 — 절대량 환산에만 사용
    source_flag = Column(String, nullable=False, default=SOURCE_MEASURED)  # measured | generated
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Formulation(Base):
    __tablename__ = "formulation"

    lot_id = Column(String, ForeignKey("lot.lot_id"), primary_key=True)
    active_material_content = Column(Float, nullable=False)  # wt%
    binder_content = Column(Float, nullable=False)           # wt%
    conductive_content = Column(Float, nullable=False)       # wt%


class ProcessCondition(Base):
    """공정 조건 — Long 포맷 (변수 확장에 스키마 변경 불필요)."""

    __tablename__ = "process_condition"
    __table_args__ = (UniqueConstraint("lot_id", "process_group", "variable_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    lot_id = Column(String, ForeignKey("lot.lot_id"), nullable=False, index=True)
    process_group = Column(String, nullable=False)  # mixing | kneading | cutting | milling | rolling | laminating
    variable_name = Column(String, nullable=False)
    value = Column(Float)


class StageMeasure(Base):
    """단계별 계측 — stage_index(M1~L2) 를 값으로 갖는 세로 구조.

    적재 시점에 FD-05 합제층 기준 환산이 완료된 값만 저장한다 (규칙 R1).
    """

    __tablename__ = "stage_measure"
    __table_args__ = (UniqueConstraint("lot_id", "stage_index"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    lot_id = Column(String, ForeignKey("lot.lot_id"), nullable=False, index=True)
    stage_index = Column(String, nullable=False)  # M1..M4, R1..R2, L1..L2
    # 3-roll mill: Milling 단계는 1회 구동에 롤갭 2개를 설정한다.
    #   gap_front_um = 전단 갭(M12, 롤1-롤2), gap_um = 후단 갭(M23, 롤2-롤3 — 출구 두께 기준)
    # Rolling/Laminating 은 단일 갭 → gap_um 만 사용.
    gap_um = Column(Float)
    gap_front_um = Column(Float)
    areal_capacity_mah_cm2 = Column(Float)
    composite_thickness_um = Column(Float)   # 합제층 기준 (집전체 차감 완료)
    composite_density_gcc = Column(Float)
    loading_mg_cm2 = Column(Float)
    total_thickness_um = Column(Float)       # 집전체 포함 원측정값 보존 (L1/L2, 화면 병기용)


class CollectorInfo(Base):
    __tablename__ = "collector_info"

    lot_id = Column(String, ForeignKey("lot.lot_id"), primary_key=True)
    foil_thickness_um = Column(Float, nullable=False)
    coating_side = Column(String, default="single")   # single | double
    collector_attached = Column(Boolean, default=True)
    coated_face_count = Column(Integer, default=1)


class ElectrodeProperty(Base):
    """최종 전극 물성. B등급(인장강도·접착력)은 결측 허용 — NULL 유지 (FP-02)."""

    __tablename__ = "electrode_property"

    lot_id = Column(String, ForeignKey("lot.lot_id"), primary_key=True)
    electrode_thickness_um = Column(Float)
    electrode_density_gcc = Column(Float)
    sheet_resistance_ohm_sq = Column(Float)
    tensile_strength_mpa = Column(Float)      # B등급 간헐 측정
    electrode_adhesion_n_cm = Column(Float)   # B등급 간헐 측정
    electrode_porosity = Column(Float)        # 자리만 유지 — 사용 금지 (규칙 R2)


class Electrochem(Base):
    """전기화학 성능 (C등급 지연 측정). 셀 평가 미완료 Lot 은 NULL 유지."""

    __tablename__ = "electrochem"

    lot_id = Column(String, ForeignKey("lot.lot_id"), primary_key=True)
    initial_discharge_capacity_mah_g = Column(Float)
    initial_coulombic_efficiency_pct = Column(Float)
    interface_resistance_ohm = Column(Float)
    cell_discharge_retention_pct = Column(Float)
    dcir_ohm = Column(Float)
    rate_capability_pct = Column(Float)


class VariableDict(Base):
    """변수 사전 (FD-03) — 변수명·단위·물리 허용 범위·확보 등급."""

    __tablename__ = "variable_dict"

    variable_name = Column(String, primary_key=True)
    unit = Column(String)
    min_value = Column(Float)
    max_value = Column(Float)
    grade = Column(String)          # A | B | C | input | const
    process_group = Column(String)
    active = Column(Boolean, default=True)
    is_constant = Column(Boolean, default=False)
    constant_value = Column(Float)
    description = Column(Text)
    version = Column(Integer, default=1)


class ModelVersion(Base):
    """모델 버전 이력 (FT-08). registry 와 1:1 짝 보관 (규칙 R8)."""

    __tablename__ = "model_version"

    version_id = Column(String, primary_key=True)       # v{major}.{minor}
    trained_at = Column(DateTime, default=datetime.datetime.utcnow)
    train_lot_count = Column(Integer, nullable=False)
    measured_ratio = Column(Float)                       # 실측/전체 구성비
    hyperparameters = Column(Text)                       # JSON
    seed = Column(Integer, nullable=False)
    registry_version = Column(String, nullable=False)    # scaling registry 짝 버전
    dataset_tag = Column(String)                         # train_{YYYYMMDD}_{lotcount}
    pseudo_label_pass_rate = Column(Float)               # FT-04 통과율
    note = Column(Text)


class PredictionLog(Base):
    """예측 이력 (FS-03)."""

    __tablename__ = "prediction_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    requested_at = Column(DateTime, default=datetime.datetime.utcnow)
    input_snapshot = Column(Text)        # JSON
    model_version_id = Column(String, ForeignKey("model_version.version_id"))
    alarm_grade = Column(String)
    user_choice = Column(String)         # 대안 수용 여부 등


class Evaluation(Base):
    """평가 결과 (FE). 학습 Lot 수를 반드시 기록한다 (NFR-08)."""

    __tablename__ = "evaluation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(String, ForeignKey("model_version.version_id"), nullable=False)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float)
    train_lot_count = Column(Integer)
    evaluated_at = Column(DateTime, default=datetime.datetime.utcnow)


_engine = None
_SessionLocal = None


def get_engine(db_url: str | None = None):
    global _engine, _SessionLocal
    if _engine is None or db_url is not None:
        _engine = create_engine(db_url or DB_URL, future=True)
        _SessionLocal = sessionmaker(bind=_engine, future=True)
    return _engine


def init_db(db_url: str | None = None):
    """테이블 생성 + 변수 사전 시드. 반환: engine."""
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    from dry_process_ai.data_access.variable_seed import seed_variable_dict

    with get_session() as session:
        seed_variable_dict(session)
        session.commit()
    return engine


def get_session() -> Session:
    if _SessionLocal is None:
        get_engine()
    return _SessionLocal()
