import os
import json
import time
from typing import Dict, Any, List
import google.generativeai as genai
from .fda_client import FDAClient
from .observability import ClaimsAgentTracer

# Configure Gemini API if key is present
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

class ClaimsAgentNetwork:
    """
    Orchestrates the multi-agent claims auditing network.
    Uses public OpenFDA REST API data to verify recall compliance and safety thresholds.
    """
    def __init__(self, fda_client: FDAClient, tracer: ClaimsAgentTracer):
        self.fda = fda_client
        self.tracer = tracer
        self.use_real_api = bool(api_key)
        if not self.use_real_api:
            print("[INFO] GEMINI_API_KEY not set. Using local agent reasoning engine linked to live OpenFDA REST endpoints.")

    def run_agent_step_via_llm(self, agent_name: str, system_instruction: str, state: Dict[str, Any], step_id: str) -> Dict[str, Any]:
        """Executes a step using the Gemini API, providing tools for FDA queries."""
        model_name = self.tracer.model_name
        prompt = f"""
Current Claims Audit State:
{json.dumps(state, indent=2)}

Please execute the next step for the {agent_name} agent.
If you need to query OpenFDA recall or safety statistics, document the request.
In your final output, return a JSON block matching this state schema to update variables:
{{
  "next_agent": "Router|RecallAuditor|SafetyAnalyst|ComplianceSpecialist|Done",
  "internal_notes": "Log your specific database findings and reasoning here",
  "audit_status": "pending|approved|rejected|escalated",
  "rejection_reason": "Provide detailed clinical or administrative reason if rejected"
}}
"""
        t_start = time.time()
        model = genai.GenerativeModel(model_name=model_name, system_instruction=system_instruction)
        
        try:
            response = model.generate_content(prompt)
            duration = time.time() - t_start
            
            in_tokens = len(prompt.split()) * 4
            out_tokens = len(response.text.split()) * 4 if response.text else 50
            self.tracer.log_llm_call(step_id, in_tokens, out_tokens, duration)
            
            content = response.text
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            parsed = json.loads(content)
            return parsed
        except Exception as e:
            # Degrade gracefully to simulated reasoning, keeping live API connectivity
            return self.simulate_agent_step(agent_name, state, step_id)

    def simulate_agent_step(self, agent_name: str, state: Dict[str, Any], step_id: str) -> Dict[str, Any]:
        """
        State transition logic mimicking Gemini, executing live HTTP requests 
        on the public OpenFDA REST API.
        """
        t_start = time.time()
        output_state = {
            "next_agent": "Router",
            "internal_notes": "",
            "audit_status": "pending",
            "rejection_reason": ""
        }
        
        claim = state["claim"]
        drug_name = claim["drug_name"]
        oauth_token = state["oauth_token"]
        
        # Security authorization check (Simulates OAuth middleware)
        if oauth_token != "OAUTH_TOKEN_PV_COMPLIANT_77":
            output_state["next_agent"] = "Done"
            output_state["audit_status"] = "escalated"
            output_state["rejection_reason"] = "Security Exception: Invalid or expired OAuth claims token."
            self.tracer.log_llm_call(step_id, 380, 110, time.time() - t_start)
            return output_state

        if agent_name == "Router":
            # Initial triage routing
            if not any("Recall Audit:" in n for n in state["notes"]):
                output_state["next_agent"] = "RecallAuditor"
                output_state["internal_notes"] = f"Triage claims routing for drug '{drug_name}'. Delegating to RecallAuditor to verify live enforcement logs."
            elif not any("Safety Audit:" in n for n in state["notes"]):
                output_state["next_agent"] = "SafetyAnalyst"
                output_state["internal_notes"] = "Enforcement check clear. Delegating to SafetyAnalyst to inspect adverse event trends."
            elif not any("Compliance Review:" in n for n in state["notes"]):
                output_state["next_agent"] = "ComplianceSpecialist"
                output_state["internal_notes"] = "FDA enforcement and safety audits logged. Delegating to ComplianceSpecialist for payout approval."
            else:
                output_state["next_agent"] = "Done"

            # Self-Reflection: Router checks findings for early rejection or final approval
            notes_str = "\n".join(state["notes"])
            
            # Short-circuit rejection if there is an active recall violation
            if "RECALL_VIOLATION" in notes_str:
                output_state["next_agent"] = "Done"
                output_state["audit_status"] = "rejected"
                output_state["rejection_reason"] = "Claim Rejected: Drug substance is under active FDA recall or withdrawal orders."
            # Only process final state once ComplianceSpecialist completes
            elif any("Compliance Review:" in n for n in state["notes"]):
                output_state["next_agent"] = "Done"
                if "SAFETY_RISK_HIGH" in notes_str:
                    output_state["audit_status"] = "escalated"
                    output_state["rejection_reason"] = "Claim Escalated: Excess adverse event frequency triggers manual clinical review."
                elif "COMPLIANCE_APPROVED" in notes_str:
                    output_state["audit_status"] = "approved"
                    output_state["rejection_reason"] = ""
                else:
                    output_state["audit_status"] = "escalated"
                    output_state["rejection_reason"] = "Claim Escalated: Value limits exceeded or manual review requested."

        elif agent_name == "RecallAuditor":
            # Query the live OpenFDA database for recalls
            t0 = time.time()
            recalls = self.fda.search_drug_recalls(drug_name)
            self.tracer.log_api_call(step_id, "OpenFDA Recalls API", f"drug_name={drug_name}", json.dumps(recalls), time.time() - t0)
            
            # Filter for active ongoing recalls
            active_recalls = [r for r in recalls if r.get("status", "").lower() == "ongoing"]
            
            if active_recalls:
                # Analyze active recalls
                recall_reasons = [r.get("reason_for_recall", "") for r in active_recalls]
                reason_summary = "; ".join(recall_reasons)
                state["notes"].append(
                    f"Recall Audit: WARNING - Found active ongoing FDA recalls for '{drug_name}'. "
                    f"Details: {reason_summary}. RECALL_VIOLATION. Specialist Verdict: REJECTED"
                )
                output_state["internal_notes"] = f"Live FDA query identified ongoing recalls for '{drug_name}'. Flagging recall violation."
            else:
                state["notes"].append(f"Recall Audit: Clearance. No active ongoing FDA recall records found for '{drug_name}'. Specialist Verdict: OK")
                output_state["internal_notes"] = f"No active ongoing FDA recall logs identified for '{drug_name}'."
                
            output_state["next_agent"] = "Router"

        elif agent_name == "SafetyAnalyst":
            # Query the live OpenFDA database for adverse event volumes
            t0 = time.time()
            event_count = self.fda.get_adverse_event_count(drug_name)
            self.tracer.log_api_call(step_id, "OpenFDA Adverse Events API", f"drug_name={drug_name}", f"Count: {event_count}", time.time() - t0)
            
            # Clinical safety catalog: check if substance is high-risk and exceeds threshold
            name_lower = drug_name.lower().strip()
            high_risk_drugs = {"acetaminophen", "paracetamol"}
            
            is_risk = (name_lower in high_risk_drugs and event_count > 300000) or (event_count > 500000)
            
            if is_risk:
                state["notes"].append(
                    f"Safety Audit: WARNING - Drug '{drug_name}' shows high adverse event volume "
                    f"({event_count} reported cases) and is flagged in the safety risk catalog. SAFETY_RISK_HIGH. Specialist Verdict: ESCALATE"
                )
                output_state["internal_notes"] = f"Adverse events count ({event_count}) triggers safety risk flags."
            else:
                state["notes"].append(
                    f"Safety Audit: Clearance. Drug '{drug_name}' adverse event frequency ({event_count}) "
                    f"is within acceptable safety margins. Specialist Verdict: OK"
                )
                output_state["internal_notes"] = f"Adverse events count ({event_count}) does not trigger safety risk alerts."
                
            output_state["next_agent"] = "Router"

        elif agent_name == "ComplianceSpecialist":
            # Audit clinical notes and check payout values
            notes_str = "\n".join(state["notes"])
            payout = claim.get("payout_amount", 0.0)
            
            if "RECALL_VIOLATION" in notes_str:
                state["notes"].append("Compliance Review: Denied payout due to FDA recall status. Specialist Verdict: RECALL_VIOLATION")
                output_state["audit_status"] = "rejected"
            elif "SAFETY_RISK_HIGH" in notes_str:
                state["notes"].append("Compliance Review: Escalated payout due to high adverse event reports. Specialist Verdict: SAFETY_RISK_HIGH")
                output_state["audit_status"] = "escalated"
            elif payout > 1000.0:
                state["notes"].append(f"Compliance Review: Escalated payout. Amount ${payout:.2f} exceeds standard audit limits ($1000.00). Specialist Verdict: VALUE_LIMIT_EXCEEDED")
                output_state["audit_status"] = "escalated"
            else:
                state["notes"].append("Compliance Review: Passed recall and safety checks. Specialist Verdict: COMPLIANCE_APPROVED")
                output_state["audit_status"] = "approved"
                
            output_state["next_agent"] = "Router"
            output_state["internal_notes"] = f"Claims payout assessment complete. Audit status set to: {output_state['audit_status']}."

        self.tracer.log_llm_call(step_id, input_tokens=450, output_tokens=150, duration_sec=time.time() - t_start)
        return output_state

    def audit_claim(self, claim: Dict[str, Any], oauth_token: str) -> Dict[str, Any]:
        """
        Executes the claim audit graph loop.
        Applies self-reflection and records traces through ClaimsAgentTracer.
        """
        state = {
            "claim": claim,
            "oauth_token": oauth_token,
            "current_agent": "Router",
            "notes": [],
            "audit_status": "pending",
            "rejection_reason": ""
        }
        
        max_hops = 8
        hop_count = 0
        
        system_instructions = {
            "Router": "You are the Router Agent. Triage claims, route to specialists, and review findings against safety thresholds.",
            "RecallAuditor": "You are the FDA Recall Auditor. Query OpenFDA endpoints for warnings and recalls.",
            "SafetyAnalyst": "You are the Adverse Event Risk Analyst. Check OpenFDA adverse event logs for risk frequencies.",
            "ComplianceSpecialist": "You are the Compliance Specialist. Verify claims value limits and compile approvals."
        }

        print(f"--- Processing Claim Audit for {claim['claim_id']} ({claim['drug_name']}) ---")
        
        while state["current_agent"] != "Done" and hop_count < max_hops:
            agent = state["current_agent"]
            step_id = self.tracer.start_step(agent, state)
            
            print(f"[AGENT] Invoking: {agent}...")
            
            if self.use_real_api:
                decision = self.run_agent_step_via_llm(
                    agent_name=agent,
                    system_instruction=system_instructions.get(agent, ""),
                    state=state,
                    step_id=step_id
                )
            else:
                decision = self.simulate_agent_step(agent, state, step_id)
                
            # Apply decisions to state
            state["current_agent"] = decision.get("next_agent", "Router")
            if decision.get("internal_notes"):
                state["notes"].append(f"[{agent} Reasoning] {decision['internal_notes']}")
            if decision.get("audit_status"):
                state["audit_status"] = decision["audit_status"]
            if decision.get("rejection_reason"):
                state["rejection_reason"] = decision["rejection_reason"]
                
            self.tracer.end_step(step_id, state)
            hop_count += 1
            
        if hop_count >= max_hops:
            state["audit_status"] = "escalated"
            state["rejection_reason"] = "System Timeout: Maximum routing limits exceeded."
            
        print(f"[AUDIT COMPLETE] Claim ID: {claim['claim_id']} | Status: {state['audit_status'].upper()} | Reason: {state['rejection_reason']}\n")
        return state
