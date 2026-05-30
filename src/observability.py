import time
import json
import os
from datetime import datetime
from typing import Dict, Any, List

# Standard Google Cloud Developer API billing structures
MODEL_PRICING = {
    "gemini-1.5-flash": {
        "input_cost_per_million": 0.075,
        "output_cost_per_million": 0.30
    },
    "gemini-2.0-flash": {
        "input_cost_per_million": 0.075,
        "output_cost_per_million": 0.30
    },
    "gemini-1.5-pro": {
        "input_cost_per_million": 1.25,
        "output_cost_per_million": 5.00
    },
    "default": {
        "input_cost_per_million": 0.075,
        "output_cost_per_million": 0.30
    }
}

class ClaimsAgentTracer:
    """
    Tracks state transitions, LLM parameters, tool latency, and developer costs
    for auditing healthcare claims in production ML operations.
    """
    def __init__(self, model_name: str = "gemini-1.5-flash"):
        self.model_name = model_name
        self.pricing = MODEL_PRICING.get(model_name, MODEL_PRICING["default"])
        self.session_id = f"claim_audit_{int(time.time())}"
        self.start_time = time.time()
        self.steps: List[Dict[str, Any]] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.total_duration = 0.0

    def start_step(self, agent_name: str, state_before: Dict[str, Any]) -> str:
        step_id = f"step_{len(self.steps) + 1}_{agent_name}"
        step_data = {
            "step_id": step_id,
            "agent": agent_name,
            "timestamp_start": datetime.utcnow().isoformat() + "Z",
            "state_before": json.loads(json.dumps(state_before)),
            "api_calls": [],
            "llm_calls": [],
            "timestamp_end": None,
            "duration_ms": 0.0,
            "state_after": None
        }
        self.steps.append(step_data)
        return step_id

    def log_llm_call(self, step_id: str, input_tokens: int, output_tokens: int, duration_sec: float):
        cost_in = (input_tokens / 1e6) * self.pricing["input_cost_per_million"]
        cost_out = (output_tokens / 1e6) * self.pricing["output_cost_per_million"]
        call_cost = cost_in + cost_out
        
        tokens_per_sec = (input_tokens + output_tokens) / duration_sec if duration_sec > 0 else 0
        
        llm_metrics = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_sec": duration_sec,
            "tokens_per_sec": round(tokens_per_sec, 2),
            "cost_usd": round(call_cost, 6)
        }
        
        for step in self.steps:
            if step["step_id"] == step_id:
                step["llm_calls"].append(llm_metrics)
                break
                
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += call_cost

    def log_api_call(self, step_id: str, api_name: str, query: str, result_summary: str, duration_sec: float):
        call_metrics = {
            "api_name": api_name,
            "query": query,
            "result_summary": result_summary[:300] + "..." if len(result_summary) > 300 else result_summary,
            "duration_sec": round(duration_sec, 3)
        }
        for step in self.steps:
            if step["step_id"] == step_id:
                step["api_calls"].append(call_metrics)
                break

    def end_step(self, step_id: str, state_after: Dict[str, Any]):
        now = datetime.utcnow().isoformat() + "Z"
        for step in self.steps:
            if step["step_id"] == step_id:
                step["timestamp_end"] = now
                start_dt = datetime.strptime(step["timestamp_start"], "%Y-%m-%dT%H:%M:%S.%fZ" if "." in step["timestamp_start"] else "%Y-%m-%dT%H:%M:%SZ")
                end_dt = datetime.strptime(now, "%Y-%m-%dT%H:%M:%S.%fZ" if "." in now else "%Y-%m-%dT%H:%M:%SZ")
                step["duration_ms"] = round((end_dt - start_dt).total_seconds() * 1000.0, 2)
                step["state_after"] = json.loads(json.dumps(state_after))
                break

    def compile_metrics(self) -> Dict[str, Any]:
        self.total_duration = time.time() - self.start_time
        avg_tokens_per_sec = 0.0
        all_calls = []
        for s in self.steps:
            all_calls.extend(s["llm_calls"])
            
        if all_calls:
            avg_tokens_per_sec = sum(c["tokens_per_sec"] for c in all_calls) / len(all_calls)
            
        summary = {
            "session_id": self.session_id,
            "model_name": self.model_name,
            "duration_seconds": round(self.total_duration, 2),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "cost_usd": round(self.total_cost, 6),
            "avg_tokens_per_sec": round(avg_tokens_per_sec, 2),
            "total_steps": len(self.steps),
            "steps": self.steps
        }
        return summary

    def save_trace(self, output_dir: str = "traces") -> str:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        filename = f"claims_trace_{self.session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        full_path = os.path.join(output_dir, filename)
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(self.compile_metrics(), f, indent=2)
        return full_path

    def print_trace_summary(self):
        metrics = self.compile_metrics()
        print("\n" + "="*55)
        print("         CLAIMS AUDITING OBSERVABILITY REPORT")
        print("="*55)
        print(f"Session ID:         {metrics['session_id']}")
        print(f"Model Name:         {metrics['model_name']}")
        print(f"Duration:           {metrics['duration_seconds']}s")
        print(f"Total Hops:         {metrics['total_steps']}")
        print(f"Total Cost (USD):   ${metrics['cost_usd']:.6f}")
        print(f"Total Tokens:       {metrics['total_tokens']} (In: {metrics['total_input_tokens']}, Out: {metrics['total_output_tokens']})")
        print(f"Avg Performance:    {metrics['avg_tokens_per_sec']} tokens/sec")
        print("-"*55)
        for step in metrics["steps"]:
            apis = [a["api_name"] for a in step["api_calls"]]
            api_str = f" [APIs: {', '.join(apis)}]" if apis else ""
            print(f"-> {step['step_id']:<25} | Latency: {step['duration_ms']:.1f}ms{api_str}")
        print("="*55 + "\n")
