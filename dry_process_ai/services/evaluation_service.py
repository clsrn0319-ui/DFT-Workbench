"""FE — 평가·리포트 서비스. 지표 산출 → DB 기록 → JSON/DOCX 리포트."""

from __future__ import annotations

from sqlalchemy.orm import Session

from dry_process_ai.core.analyze.evaluation import (
    EvaluationReport,
    closed_loop_feedback,
    evaluate_model,
    save_report,
    save_report_docx,
)
from dry_process_ai.core.infer.predictor import Predictor
from dry_process_ai.data_access.db import Evaluation
from dry_process_ai.data_access.repository import fetch_dataset


def run_evaluation(
    session: Session,
    predictor: Predictor,
    train_lot_count: int,
    write_docx: bool = False,
) -> tuple[EvaluationReport, dict]:
    """평가 실행 + evaluation 테이블 기록 + 리포트 파일 생성 + 폐루프 항목 식별."""
    df = fetch_dataset(session)  # 내부에서 measured 만 평가 (규칙 R3)
    report = evaluate_model(predictor, df, train_lot_count)

    for name, m in report.a_grade.items():
        if m.get("mape_pct") is not None:
            session.add(Evaluation(
                version_id=report.model_version, metric_name=f"mape_{name}",
                metric_value=m["mape_pct"], train_lot_count=train_lot_count,
            ))
    if report.consistency.get("violation_rate_pct") is not None:
        session.add(Evaluation(
            version_id=report.model_version, metric_name="constraint_violation_rate_pct",
            metric_value=report.consistency["violation_rate_pct"], train_lot_count=train_lot_count,
        ))
    session.commit()

    save_report(report)
    if write_docx:
        save_report_docx(report)
    return report, closed_loop_feedback(report)
