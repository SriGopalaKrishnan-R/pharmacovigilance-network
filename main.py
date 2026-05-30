import os
import sys
import argparse
from src.fda_client import FDAClient
from src.observability import ClaimsAgentTracer
from src.agent_network import ClaimsAgentNetwork
from src.evaluator import ClaimsEvaluator

def run_simulation(claim_id: str, drug: str, patient: str, qty: int, dosage: str, payout: float, token: str, model: str):
    fda = FDAClient()
    tracer = ClaimsAgentTracer(model_name=model)
    orchestrator = ClaimsAgentNetwork(fda, tracer)
    
    claim = {
        "claim_id": claim_id,
        "patient_name": patient,
        "drug_name": drug,
        "prescribed_quantity": qty,
        "dosage": dosage,
        "payout_amount": payout
    }
    
    print("\nStarting PharmacoVigilance claims audit simulation...")
    print(f"Claim ID:     {claim_id}")
    print(f"Patient:      {patient}")
    print(f"Drug Name:    {drug}")
    print(f"Payout Limit: ${payout:.2f}")
    print("=" * 60)
    
    final_state = orchestrator.audit_claim(claim, token)
    
    # Save trace and print summary
    trace_path = tracer.save_trace()
    tracer.print_trace_summary()
    print(f"Detailed execution trace logged to: {trace_path}\n")

def run_evals(model: str):
    evaluator = ClaimsEvaluator(model_name=model)
    evaluator.run_evaluations()

def main():
    parser = argparse.ArgumentParser(description="PharmacoVigilance Claims & FDA Warnings Agent CLI.")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Sim parser
    sim_parser = subparsers.add_parser("sim", help="Audit a single medical drug claim")
    sim_parser.add_argument("--claim_id", type=str, default="CLM_901", help="Target claim ID")
    sim_parser.add_argument("--drug", type=str, required=True, help="Prescribed chemical substance (e.g. Metformin, Valdecoxib)")
    sim_parser.add_argument("--patient", type=str, default="Jane Doe", help="Patient name")
    sim_parser.add_argument("--qty", type=int, default=30, help="Prescribed quantity")
    sim_parser.add_argument("--dosage", type=str, default="10mg", help="Drug dosage")
    sim_parser.add_argument("--payout", type=float, default=120.00, help="Claims payout amount")
    sim_parser.add_argument("--token", type=str, default="OAUTH_TOKEN_PV_COMPLIANT_77", help="OAuth bearer token")
    sim_parser.add_argument("--model", type=str, default="gemini-1.5-flash", help="Generative model name")
    
    # Eval parser
    eval_parser = subparsers.add_parser("eval", help="Execute the claims verification suite")
    eval_parser.add_argument("--model", type=str, default="gemini-1.5-flash", help="Generative model name")
    
    args = parser.parse_args()
    
    if args.command == "sim":
        run_simulation(
            args.claim_id, args.drug, args.patient, args.qty, 
            args.dosage, args.payout, args.token, args.model
        )
    elif args.command == "eval":
        run_evals(args.model)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
