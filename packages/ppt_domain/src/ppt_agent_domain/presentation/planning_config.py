"""Product planning roles. Shared by application assembly and integration tests."""
from dataclasses import dataclass, field
import os

from agent_harness.core.models import init_chat_model


@dataclass
class PlanningConfig:
    planning_model: str = field(default_factory=lambda: os.environ.get('PPT_AGENT_PLANNING_MODEL','').strip() or 'deepseek:deepseek-flash')
    review_model: str = field(default_factory=lambda: os.environ.get('PPT_AGENT_PLANNING_REVIEW_MODEL','').strip() or 'qwen:qwen3.8-flash')
    revision_model: str = field(default_factory=lambda: os.environ.get('PPT_AGENT_PLANNING_REVISION_MODEL','').strip() or 'deepseek:deepseek-flash')
    max_output_tokens: int = 18000
    timeout_seconds: float = 300
    max_calls_per_phase: int = 7
    max_compactions_per_phase: int = 1
    hard_budget_cny: float = 3.0
    max_context_tokens: int = 120000

    def spec(self, phase):
        return {'planning':self.planning_model, 'review':self.review_model, 'revision':self.revision_model}[phase]

    def parameters(self, phase):
        spec = self.spec(phase)
        common = dict(timeout=self.timeout_seconds, max_retries=0)
        if spec.startswith('deepseek:'):
            return dict(common, max_tokens=self.max_output_tokens, reasoning_effort='low',
                        extra_body={'thinking':{'type':'enabled'}})
        if spec.startswith('qwen:'):
            return dict(common, max_completion_tokens=self.max_output_tokens, reasoning_effort='low')
        raise ValueError('Explicit planning role must use an existing DeepSeek/Qwen adapter; no silent fallback')

    def create_model(self, phase):
        return init_chat_model(self.spec(phase), **self.parameters(phase))

    def rates(self, phase):
        # Frozen historical peak-rate ESTIMATES, not a claim of current price.
        return (2., .04, 8.) if self.spec(phase).startswith('deepseek:') else (.8, .8, 2.7)
