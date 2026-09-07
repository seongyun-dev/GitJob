"""Streamlit UI for the temporary JobKorea backend-posting crawler."""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import streamlit as st

from JobKorea_Collector_V1.client import JobKoreaHttpError
from JobKorea_Collector_V1.crawler import (
    CrawlConfig,
    CrawlResult,
    JobKoreaCrawler,
    write_outputs,
)

DEFAULT_START_DATE = date(2026, 8, 1)
DEFAULT_END_DATE = date(2026, 8, 31)


def main() -> None:
    st.set_page_config(
        page_title="JobKorea Backend Crawler",
        page_icon="🧭",
        layout="wide",
    )
    _apply_styles()
    _initialize_session_state()

    st.title("잡코리아 백엔드 채용 공고 수집기")
    st.caption(
        "등록 기간, 상세 본문, 이미지 OCR 조건을 설정해 공고를 수집하고 "
        "기술 스택을 바로 확인합니다."
    )

    settings, submitted = _render_settings()
    if submitted:
        _execute_crawl(settings)

    result = st.session_state.get("jobkorea_result")
    paths = st.session_state.get("jobkorea_paths", {})
    error = st.session_state.get("jobkorea_error")
    if error:
        st.error(error)
    if result is None:
        st.info("왼쪽 설정을 확인한 뒤 ‘수집 시작’을 눌러 주세요.")
        _render_collection_notes()
        return

    _render_result(result, paths)


def _initialize_session_state() -> None:
    st.session_state.setdefault("jobkorea_result", None)
    st.session_state.setdefault("jobkorea_paths", {})
    st.session_state.setdefault("jobkorea_error", None)


def _render_settings() -> tuple[dict[str, Any], bool]:
    with st.sidebar:
        st.header("수집 설정")
        st.caption("대상 분류: 백엔드개발자 (1000229)")
        with st.form("jobkorea_crawl_form", clear_on_submit=False):
            start_date = st.date_input(
                "등록 시작일",
                value=DEFAULT_START_DATE,
                format="YYYY-MM-DD",
            )
            end_date = st.date_input(
                "등록 종료일",
                value=DEFAULT_END_DATE,
                format="YYYY-MM-DD",
            )
            max_pages = st.number_input(
                "최대 목록 페이지",
                min_value=1,
                max_value=500,
                value=100,
                step=1,
            )
            request_delay = st.number_input(
                "목록 요청 간격 (초)",
                min_value=0.0,
                max_value=30.0,
                value=0.8,
                step=0.1,
            )
            detail_delay = st.number_input(
                "상세/이미지 요청 간격 (초)",
                min_value=0.0,
                max_value=30.0,
                value=0.5,
                step=0.1,
            )
            fetch_details = st.checkbox("상세 공고 본문 수집", value=True)
            ocr_images = st.checkbox(
                "이미지 공고 OCR 적용",
                value=True,
                disabled=not fetch_details,
                help="PaddleOCR 설치 후 이미지 안의 한국어 본문도 추출합니다.",
            )
            ocr_device = st.selectbox(
                "OCR 실행 장치",
                options=("cpu", "gpu:0"),
                disabled=not fetch_details or not ocr_images,
            )
            ocr_min_confidence = st.slider(
                "OCR 최소 신뢰도",
                min_value=0.0,
                max_value=1.0,
                value=0.35,
                step=0.05,
                disabled=not fetch_details or not ocr_images,
            )
            max_images = st.number_input(
                "공고당 OCR 이미지 최대 개수",
                min_value=1,
                max_value=100,
                value=20,
                step=1,
                disabled=not fetch_details or not ocr_images,
            )
            output_dir = st.text_input(
                "결과 저장 폴더",
                value="data/jobkorea",
            )
            submitted = st.form_submit_button(
                "수집 시작",
                type="primary",
                width="stretch",
            )

    settings = {
        "start_date": start_date,
        "end_date": end_date,
        "max_pages": int(max_pages),
        "request_delay": float(request_delay),
        "detail_delay": float(detail_delay),
        "fetch_details": bool(fetch_details),
        "ocr_images": bool(ocr_images and fetch_details),
        "ocr_device": str(ocr_device),
        "ocr_min_confidence": float(ocr_min_confidence),
        "max_images_per_posting": int(max_images),
        "output_dir": output_dir.strip(),
    }
    return settings, submitted


def _execute_crawl(settings: dict[str, Any]) -> None:
    st.session_state["jobkorea_result"] = None
    st.session_state["jobkorea_paths"] = {}
    st.session_state["jobkorea_error"] = None
    progress_bar = st.progress(0.0, text="수집 준비 중")
    status = st.empty()

    try:
        output_dir = Path(settings["output_dir"] or "data/jobkorea")
        config = CrawlConfig(
            start_date=settings["start_date"],
            end_date=settings["end_date"],
            output_dir=output_dir,
            max_pages=settings["max_pages"],
            request_delay=settings["request_delay"],
            detail_delay=settings["detail_delay"],
            fetch_details=settings["fetch_details"],
            ocr_images=settings["ocr_images"],
            ocr_device=settings["ocr_device"],
            ocr_min_confidence=settings["ocr_min_confidence"],
            max_images_per_posting=settings["max_images_per_posting"],
        )
        crawler = JobKoreaCrawler(config)
        result = crawler.run(
            progress_callback=lambda event: _update_progress(
                event,
                progress_bar,
                status,
            )
        )
        paths = write_outputs(result, config.output_dir)
    except (JobKoreaHttpError, OSError, ValueError) as error:
        st.session_state["jobkorea_error"] = f"수집 실패: {error}"
        progress_bar.progress(1.0, text="수집 실패")
        return

    st.session_state["jobkorea_result"] = result
    st.session_state["jobkorea_paths"] = paths
    progress_bar.progress(1.0, text="수집 완료")
    status.success(f"{len(result.batch.records)}건 수집 완료")


def _update_progress(
    event: dict[str, Any],
    progress_bar: Any,
    status: Any,
) -> None:
    stage = event.get("stage")
    current = int(event.get("current", 0))
    total = max(int(event.get("total", 1)), 1)
    ratio = current / total
    if stage == "list":
        progress = 0.2 * ratio
    elif stage == "detail":
        progress = 0.2 + 0.75 * ratio
    elif stage == "complete":
        progress = 1.0
    else:
        progress = min(0.1, ratio)
    message = str(event.get("message", "처리 중"))
    progress_bar.progress(min(max(progress, 0.0), 1.0), text=message)
    status.info(message)


def _render_result(result: CrawlResult, paths: dict[str, Path]) -> None:
    manifest = result.manifest
    stats = manifest["stats"]
    ocr = manifest["ocr"]
    ocr_stats = ocr.get("stats", {})
    technology_count = stats["technology_mentions"]
    completed_ocr = ocr_stats.get("postings_completed", 0)

    metric_columns = st.columns(5)
    metric_columns[0].metric("수집 공고", stats["records_written"])
    metric_columns[1].metric("상세 처리", stats["detail_requests"])
    metric_columns[2].metric("기술 스택 언급", technology_count)
    metric_columns[3].metric("OCR 완료 공고", completed_ocr)
    metric_columns[4].metric("OCR 처리 이미지", ocr_stats.get("images_processed", 0))

    st.caption(
        f"수집 시각: {manifest['collection']['collected_at']} · "
        f"저장 위치: {Path(paths['json']).parent if paths else '없음'}"
    )
    _render_downloads(paths)

    overview_tab, technology_tab, ocr_tab, manifest_tab = st.tabs(
        ["공고 목록", "기술 스택", "OCR 상태", "실행 정보"]
    )
    with overview_tab:
        _render_postings(result)
    with technology_tab:
        _render_technologies(result)
    with ocr_tab:
        _render_ocr(ocr, manifest.get("warnings", []))
    with manifest_tab:
        st.json(manifest)


def _render_downloads(paths: dict[str, Path]) -> None:
    if not paths:
        return
    download_columns = st.columns(3)
    download_specs = (
        ("json", "JSON 다운로드", "application/json"),
        ("csv", "CSV 다운로드", "text/csv"),
        ("manifest", "Manifest 다운로드", "application/json"),
    )
    for column, (key, label, mime) in zip(download_columns, download_specs):
        path = Path(paths[key])
        if path.exists():
            column.download_button(
                label,
                data=path.read_bytes(),
                file_name=path.name,
                mime=mime,
                key=f"download_{key}",
                width="stretch",
            )


def _render_postings(result: CrawlResult) -> None:
    records = result.batch.records
    if not records:
        st.info("조건에 맞는 공고가 없습니다. 페이지 수나 등록 기간을 확인해 주세요.")
        return

    rows = []
    for record in records:
        rows.append(
            {
                "공고 ID": record.source_posting_id,
                "회사": record.company_name,
                "제목": record.title,
                "경력": record.career_level or "",
                "지역": record.region or "",
                "본문": record.body_status.value,
                "마감": record.posting_status.value,
                "기술 언급": len(record.technology_mentions),
                "등록일": record.posted_at.date().isoformat()
                if record.posted_at
                else "",
            }
        )
    st.dataframe(rows, hide_index=True, width="stretch")

    selected_index = st.selectbox(
        "본문/OCR 결과 확인",
        options=range(len(records)),
        format_func=lambda index: (
            f"{records[index].company_name} · {records[index].title}"
        ),
    )
    selected = records[selected_index]
    st.text_area(
        "수집 본문",
        value=selected.description_text or "본문이 없거나 접근할 수 없습니다.",
        height=320,
        disabled=True,
    )


def _render_technologies(result: CrawlResult) -> None:
    counts: Counter[tuple[str, str]] = Counter()
    examples: dict[tuple[str, str], str] = {}
    for record in result.batch.records:
        for mention in record.technology_mentions:
            technology_id = mention.source_technology_id or mention.raw_technology
            key = (technology_id, mention.requirement_type.value)
            counts[key] += 1
            examples.setdefault(key, mention.evidence_text)

    if not counts:
        st.info("추출된 기술 스택이 없습니다.")
        return
    rows = [
        {
            "기술 ID": technology_id,
            "요구 수준": requirement_type,
            "언급 수": count,
            "근거 예시": examples[(technology_id, requirement_type)],
        }
        for (technology_id, requirement_type), count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
    ]
    st.dataframe(rows, hide_index=True, width="stretch")


def _render_ocr(ocr: dict[str, Any], warnings: list[str]) -> None:
    if not ocr.get("enabled"):
        st.info("OCR이 비활성화된 실행입니다.")
    st.json(
        {
            "enabled": ocr.get("enabled"),
            "backend": ocr.get("backend"),
            "language": ocr.get("language"),
            "device": ocr.get("device"),
            "stats": ocr.get("stats", {}),
        }
    )
    postings = ocr.get("postings", [])
    if postings:
        st.dataframe(postings, hide_index=True, width="stretch")
    if warnings:
        st.subheader("경고")
        for warning in warnings:
            st.warning(warning)


def _render_collection_notes() -> None:
    with st.expander("사용 안내", expanded=True):
        st.markdown(
            """
            1. 날짜는 등록일 기준이며 종료일을 포함합니다.
            2. 상세 본문을 켜면 텍스트 공고와 이미지 공고를 함께 처리합니다.
            3. 이미지 OCR은 PaddleOCR 설치 시 활성화되고, 미설치 상태에서도
               텍스트 공고 수집은 계속됩니다.
            4. 결과는 JSON, CSV, manifest 세 파일로 저장됩니다.
            """
        )


def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 2rem; padding-bottom: 3rem; }
        [data-testid="stMetric"] { border: 1px solid #e6eaf0; padding: 0.8rem; border-radius: 0.6rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
