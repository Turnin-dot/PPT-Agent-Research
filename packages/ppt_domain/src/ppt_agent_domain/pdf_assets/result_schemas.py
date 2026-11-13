"""Pydantic contracts for canonical PDF asset tool results."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

NonEmpty = Annotated[str, Field(min_length=1)]
Revision = Annotated[StrictInt, Field(ge=1)]
Page = Annotated[StrictInt, Field(ge=1)]
Count = Annotated[StrictInt, Field(ge=0)]


class PdfResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FlexibleRecord(BaseModel):
    """Typed common fields while retaining provider-specific diagnostics."""

    model_config = ConfigDict(extra="allow")


class ModelUsage(PdfResultModel):
    input_tokens: Count
    output_tokens: Count
    reasoning_tokens: Count | None = None
    cached_tokens: Count | None = None


class ReviewScope(PdfResultModel):
    pages: list[Page]
    asset_ids: list[str]


class ReviewCoverage(PdfResultModel):
    status: Literal["complete", "incomplete"]
    expected_pages: list[Page]
    covered_pages: list[Page]
    missing_pages: list[Page]
    expected_asset_ids: list[str]
    covered_asset_ids: list[str]
    missing_asset_ids: list[str]
    failed_batches: list[str]


class ReviewIssue(FlexibleRecord):
    issue_type: NonEmpty
    description: NonEmpty
    asset_id: str = ""
    source_page: Page | None = None
    repair_action: str = ""


class ReviewExecutionError(FlexibleRecord):
    message: str = ""
    batch_id: str = ""
    error_type: str = ""


class ReviewConsistency(PdfResultModel):
    status: NonEmpty
    findings: list[ReviewIssue]


class ParsePdfResult(PdfResultModel):
    execution_status: Literal["succeeded"]
    reused: StrictBool
    manifest_path: NonEmpty
    revision: Revision
    review_verdict: Literal["not_reviewed", "pass", "needs_repair", "uncertain"]
    asset_counts: dict[str, Count]
    mineru_result_dir: str = ""
    diagnostics: list[Any]


class ViewPdfPageResult(PdfResultModel):
    execution_status: Literal["succeeded"]
    read_only: Literal[True]
    page_number: Page
    image_path: NonEmpty
    pixel_width: Annotated[StrictInt, Field(gt=0)]
    pixel_height: Annotated[StrictInt, Field(gt=0)]
    pdf_width_points: Annotated[StrictFloat, Field(gt=0)]
    pdf_height_points: Annotated[StrictFloat, Field(gt=0)]
    coordinate_system: NonEmpty
    dpi: Annotated[StrictInt, Field(gt=0)]
    description: str | None = None
    internal_model: str | None = None
    model_usage: ModelUsage | None = None

    @model_validator(mode="after")
    def visual_fields_are_complete(self) -> ViewPdfPageResult:
        visual = (self.description, self.internal_model, self.model_usage)
        if any(item is not None for item in visual) and not all(
            item is not None for item in visual
        ):
            raise ValueError("description, internal_model and model_usage must appear together")
        return self


class ReviewPdfAssetsResult(PdfResultModel):
    review_contract: str = "legacy"
    full_document_coverage: StrictBool = False
    reused_batch_count: Count = 0
    execution_status: Literal["succeeded"]
    review_run_status: Literal["complete", "partial"]
    review_verdict: Literal["pass", "needs_repair", "uncertain"]
    applicability: Literal["current", "stale"]
    is_verified: StrictBool
    manifest_revision: Revision
    scope: ReviewScope
    coverage: ReviewCoverage
    batch_count: Count
    completed_batch_count: Count
    failed_batch_count: Count
    estimated_unique_material_tokens: Count
    estimated_planned_input_tokens: Count
    estimated_attempted_input_tokens: Count
    issue_count: Count
    issues: list[ReviewIssue]
    report_path: NonEmpty
    plan_path: NonEmpty
    internal_model_usage: ModelUsage
    internal_models: list[str]
    execution_errors: list[ReviewExecutionError]
    consistency: ReviewConsistency

    @model_validator(mode="after")
    def validate_review_semantics(self) -> ReviewPdfAssetsResult:
        if self.issue_count != len(self.issues):
            raise ValueError("issue_count must equal len(issues)")
        complete = (
            self.coverage.status == "complete"
            and not self.coverage.missing_pages
            and not self.coverage.missing_asset_ids
            and not self.coverage.failed_batches
            and self.failed_batch_count == 0
            and not self.execution_errors
        )
        if (self.review_run_status == "complete") != complete:
            raise ValueError("review_run_status must match coverage and batch failures")
        verified = (
            complete
            and self.review_verdict == "pass"
            and self.applicability == "current"
            and self.consistency.status == "pass"
        )
        if self.is_verified != verified:
            raise ValueError("is_verified must be derived from current complete passing coverage")
        return self


class CropPdfAssetResult(PdfResultModel):
    execution_status: Literal["succeeded"]
    operation: Literal["crop_asset"]
    asset_id: NonEmpty
    asset_version: Revision
    manifest_revision: Revision
    image_path: NonEmpty
    previous_reviews: Literal["stale"]


class UpdateAssetMappingResult(PdfResultModel):
    execution_status: Literal["succeeded"]
    operation: Literal["update_mapping"]
    asset_id: NonEmpty
    asset_version: Revision
    manifest_revision: Revision
    previous_reviews: Literal["stale"]


class RegisteredIssue(FlexibleRecord):
    issue_id: NonEmpty
    source_page: Page
    issue_type: NonEmpty
    description: NonEmpty
    asset_id: str
    status: Literal["unresolved"]
    created_at: NonEmpty


class RegisterPdfAssetIssueResult(PdfResultModel):
    execution_status: Literal["succeeded"]
    operation: Literal["register_issue"]
    manifest_revision: Revision
    issue: RegisteredIssue
    assets_modified: Literal[False]


class ReRecognizePdfRegionResult(PdfResultModel):
    execution_status: Literal["succeeded"]
    operation: Literal["re_recognize_region"]
    asset_id: NonEmpty
    asset_version: Revision
    manifest_revision: Revision
    recognized_text: str
    report_path: NonEmpty
    internal_model_usage: ModelUsage
    internal_model: NonEmpty


class CurrentReview(FlexibleRecord):
    report_id: str | None = None
    scope: Any = None
    review_verdict: str | None = None
    is_verified: StrictBool


class ManifestDiagnostic(FlexibleRecord):
    field: NonEmpty
    reason: NonEmpty


class ValidatePdfAssetManifestResult(PdfResultModel):
    pages: list[FlexibleRecord] = Field(default_factory=list)
    execution_status: Literal["succeeded"]
    validation_status: Literal["pass", "issues_found"]
    read_only: Literal[True]
    manifest_path: NonEmpty
    manifest_revision: Revision
    source_page_count: Count | None
    asset_count: Count
    current_reviews: list[CurrentReview]
    errors: list[ManifestDiagnostic]
    warnings: list[ManifestDiagnostic]

    @model_validator(mode="after")
    def validation_status_matches_errors(self) -> ValidatePdfAssetManifestResult:
        expected = "issues_found" if self.errors else "pass"
        if self.validation_status != expected:
            raise ValueError("validation_status must match errors")
        return self


class PreparePdfAssetsResult(PdfResultModel):
    execution_status: Literal["succeeded"]
    preparation_status: Literal["complete", "partial"]
    parse: ParsePdfResult
    review: ReviewPdfAssetsResult
    repairs: list[CropPdfAssetResult]
    unresolved_issues: list[Any]
    stopped_reason: Literal[
        "complete",
        "review_execution_failed",
        "auto_repair_disabled",
        "repair_limit_or_no_safe_action",
    ]
    elapsed_seconds: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def preparation_matches_review(self) -> PreparePdfAssetsResult:
        expected = "complete" if self.review.review_run_status == "complete" else "partial"
        if self.preparation_status != expected:
            raise ValueError("preparation_status must match review_run_status")
        return self


def _json_summary(value: BaseModel, *, omit: set[str] | None = None) -> str:
    payload = value.model_dump(mode="json", exclude=omit or set())
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_parse_result(value: ParsePdfResult) -> str:
    return _json_summary(value)


def render_page_result(value: ViewPdfPageResult) -> str:
    return _json_summary(value)


def render_review_result(value: ReviewPdfAssetsResult) -> str:
    payload = value.model_dump(mode="json", exclude={"issues", "execution_errors"})
    # Keep decision data, not repeated full ID inventories, in model history.
    payload["scope"] = {"pages": value.scope.pages, "asset_count": len(value.scope.asset_ids)}
    coverage = value.coverage
    payload["coverage"] = {"status": coverage.status,
        "expected_pages": coverage.expected_pages, "covered_pages": coverage.covered_pages,
        "missing_pages": coverage.missing_pages, "expected_asset_count": len(coverage.expected_asset_ids),
        "covered_asset_count": len(coverage.covered_asset_ids),
        "missing_asset_ids": coverage.missing_asset_ids, "failed_batches": coverage.failed_batches}
    payload["consistency"] = {"status": value.consistency.status, "finding_count": len(value.consistency.findings)}
    payload["issue_preview"] = [item.model_dump(mode="json") for item in value.issues[:5]]
    payload["execution_error_preview"] = [
        item.model_dump(mode="json") for item in value.execution_errors[:3]
    ]
    payload["summary_note"] = (
        "coverage complete only means every required range was checked; review_verdict pass "
        "and is_verified=true are separate requirements."
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_mutation_result(value: BaseModel) -> str:
    return _json_summary(value)


def render_manifest_validation(value: ValidatePdfAssetManifestResult) -> str:
    return _json_summary(value)


def render_prepare_result(value: PreparePdfAssetsResult) -> str:
    payload = {
        "execution_status": value.execution_status,
        "preparation_status": value.preparation_status,
        "manifest_path": value.parse.manifest_path,
        "manifest_revision": value.review.manifest_revision,
        "parse_reused": value.parse.reused,
        "review_run_status": value.review.review_run_status,
        "review_verdict": value.review.review_verdict,
        "applicability": value.review.applicability,
        "is_verified": value.review.is_verified,
        "coverage": json.loads(render_review_result(value.review))["coverage"],
        "full_document_coverage": value.review.full_document_coverage,
        "issue_count": value.review.issue_count,
        "report_path": value.review.report_path,
        "plan_path": value.review.plan_path,
        "repair_count": len(value.repairs),
        "unresolved_issue_count": len(value.unresolved_issues),
        "stopped_reason": value.stopped_reason,
        "elapsed_seconds": value.elapsed_seconds,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
