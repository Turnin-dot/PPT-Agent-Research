"""Small per-call usage ledger. No model configuration or scheduling policy."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from threading import Lock
import time
import uuid

from .messages import Usage

_collector = ContextVar('model_call_collector',default=None)


@contextmanager
def capture_model_calls():
    records=[]
    token=_collector.set((records,Lock()))
    try:
        yield records
    finally:
        _collector.reset(token)


def invoke_metered(model,messages,*,category='internal_vision',attempt=1):
    """One logical invoke; hidden SDK HTTP retries are explicitly unknown."""
    started=time.perf_counter()
    record=dict(call_id=uuid.uuid4().hex,category=category,model=getattr(model,'model',type(model).__name__),
                attempt=attempt,is_retry=attempt>1,status='failed',usage=None,sdk_retry_count=None)
    try:
        response=model.invoke(messages)
        record.update(status='succeeded',usage=asdict(response.usage))
        return response
    except Exception as exc:
        record['error_type']=type(exc).__name__
        raise
    finally:
        record['elapsed_seconds']=time.perf_counter()-started
        collector=_collector.get()
        if collector is not None:
            with collector[1]: collector[0].append(record)


class RunMeter:
    def __init__(self):
        self.calls=[]
        self.tool_count=0
        self.tool_failures=0
        self.tool_seconds=0.0

    def add(self,record):
        self.calls.append(record)

    def summary(self):
        categories={}
        total=Usage()
        for record in self.calls:
            value=record.get('usage')
            item=categories.setdefault(record['category'],dict(calls=0,failures=0,retries=0,usage=Usage(),unknown_usage_calls=0))
            item['calls']+=1
            item['failures']+=record['status']=='failed'
            item['retries']+=bool(record.get('is_retry'))
            if value is None:
                item['unknown_usage_calls']+=1
            else:
                use=Usage(**value)
                item['usage']=item['usage']+use
                total=total+use
        for value in categories.values(): value['usage']=asdict(value['usage'])
        return dict(usage_by_category=categories,total_known_usage=asdict(total),
                    tool_calls=self.tool_count,tool_failures=self.tool_failures,
                    tool_elapsed_seconds_sum=self.tool_seconds,sdk_retry_count=None,
                    note='usage subsets are not extra tokens; unknown SDK HTTP retries/failed-call billing are not zero')
