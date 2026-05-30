import time
from typing import Dict, Any, List
from .fda_client import FDAClient
from .observability import ClaimsAgentTracer
from .agent_network import ClaimsAgentNetwork

# Enterprise Claim Audit Test Scenarios using actual market drugs
CLAIM_SCENARIOS = [
    {
        "id": "CLAIM_SCENARIO_1",
        "name": "Market Withdrawn Recall Audit (Valdecoxib)",
        "claim": {
            "claim_id": "CLM_201",
            "patient_name": "Alice Johnson",
            "drug_name": "Valdecoxib",
            "prescribed_quantity": 30,
            "dosage": "10mg",
            "payout_amount": 150.00
        },
        "oauth_token": "OAUTH_TOKEN_PV_COMPLIANT_77",
        "expected_status": "rejected",
        "reasoning": "Should query OpenFDA and find Valdecoxib (Bextra) recall/withdrawal orders, resulting in claim rejection."
    },
    {
        "id": "CLAIM_SCENARIO_2",
        "name": "Standard Safe Drug Approval (Metformin)",
        "claim": {
            "claim_id": "CLM_202",
            "patient_name": "Bob Smith",
            "drug_name": "Metformin",
            "prescribed_quantity": 60,
            "dosage": "500mg",
            "payout_amount": 45.00
        },
        "oauth_token": "OAUTH_TOKEN_PV_COMPLIANT_77",
        "expected_status": "approved",
        "reasoning": "Metformin is a standard safe active drug with no general recalls and low adverse reports."
    },
    {
        "id": "CLAIM_SCENARIO_3",
        "name": "High Adverse Event Risk Signal (Acetaminophen)",
        "claim": {
            "claim_id": "CLM_203",
            "patient_name": "Charlie Brown",
            "drug_name": "Acetaminophen",
            "prescribed_quantity": 90,
            "dosage": "325mg",
            "payout_amount": 25.00
        },
        "oauth_token": "OAUTH_TOKEN_PV_COMPLIANT_77",
        "expected_status": "escalated",
        "reasoning": "Acetaminophen has very high reports in OpenFDA database, exceeding the 5,000 safety threshold, triggering escalation."
    },
    {
        "id": "CLAIM_SCENARIO_4",
        "name": "High Payout Value Limit (Lisinopril)",
        "claim": {
            "claim_id": "CLM_204",
            "patient_name": "Diana Prince",
            "drug_name": "Lisinopril",
            "prescribed_quantity": 30,
            "dosage": "20mg",
            "payout_amount": 1200.00
        },
        "oauth_token": "OAUTH_TOKEN_PV_COMPLIANT_77",
        "expected_status": "escalated",
        "reasoning": "Lisinopril is safe, but the claims payout amount ($1200.00) exceeds the compliance policy limit ($1000.00)."
    },
    {
        "id": "CLAIM_SCENARIO_5",
        "name": "OAuth Security Token Expiry (Lisinopril)",
        "claim": {
            "claim_id": "CLM_205",
            "patient_name": "Evan Wright",
            "drug_name": "Lisinopril",
            "prescribed_quantity": 30,
            "dosage": "10mg",
            "payout_amount": 35.00
        },
        "oauth_token": "OAUTH_TOKEN_EXPIRED_99",
        "expected_status": "escalated",
        "reasoning": "Should fail initial OAuth gateway verification checks and stop workflow."
    }
]

class ClaimsEvaluator:
    """Runs tests scenarios, asserting claim decisions and checking telemetry records."""
    def __init__(self, model_name: str = "gemini-1.5-flash"):
        self.model_name = model_name

    def run_evaluations(self) -> Dict[str, Any]:
        results = []
        passed_count = 0
        total_tokens = 0
        total_cost = 0.0
        
        print("\n" + "="*70)
        print("        PHARMACOVIGILANCE CLAIMS EVALUATION PIPELINE RUN")
        print("="*70)
        
        fda = FDAClient()
        
        for sc in CLAIM_SCENARIOS:
            tracer = ClaimsAgentTracer(model_name=self.model_name)
            orchestrator = ClaimsAgentNetwork(fda, tracer)
            
            print(f"[{sc['id']}] Auditing: '{sc['name']}'...")
            t0 = time.time()
            
            final_state = orchestrator.audit_claim(
                claim=sc["claim"],
                oauth_token=sc["oauth_token"]
            )
            
            duration = time.time() - t0
            metrics = tracer.compile_metrics()
            
            passed = final_state["audit_status"] == sc["expected_status"]
            if passed:
                passed_count += 1
                
            total_tokens += metrics["total_tokens"]
            total_cost += metrics["cost_usd"]
            
            trace_path = tracer.save_trace()
            
            results.append({
                "scenario_id": sc["id"],
                "scenario_name": sc["name"],
                "expected": sc["expected_status"],
                "actual": final_state["audit_status"],
                "passed": passed,
                "duration_seconds": round(duration, 2),
                "total_tokens": metrics["total_tokens"],
                "cost_usd": metrics["cost_usd"],
                "trace_file": trace_path,
                "rejection_reason": final_state["rejection_reason"]
            })
            
            status_symbol = "PASS" if passed else "FAIL"
            print(f"[{sc['id']}] Result: [{status_symbol}] | Actual: {final_state['audit_status']} | Expected: {sc['expected_status']}")
            print(f"      Duration: {duration:.2f}s | Tokens: {metrics['total_tokens']} | Cost: ${metrics['cost_usd']:.6f}")
            print("-" * 70)
            
        success_rate = (passed_count / len(CLAIM_SCENARIOS)) * 100.0
        summary = {
            "model_name": self.model_name,
            "total_claims": len(CLAIM_SCENARIOS),
            "passed_claims": passed_count,
            "success_rate_percent": round(success_rate, 2),
            "total_tokens_consumed": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "scenarios": results
        }
        
        print("\n" + "="*70)
        print("                    EVALUATION SCORECARD SUMMARY")
        print("="*70)
        print(f"Model Name:          {summary['model_name']}")
        print(f"Claims Evaluated:    {summary['total_claims']}")
        print(f"Passed Asserts:      {summary['passed_claims']} / {summary['total_claims']}")
        print(f"Success Rate:        {summary['success_rate_percent']}%")
        print(f"Total Tokens:        {summary['total_tokens_consumed']}")
        print(f"Total LLM Cost:      ${summary['total_cost_usd']:.6f}")
        print("="*70 + "\n")
        
        return summary
