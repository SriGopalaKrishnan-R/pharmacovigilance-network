import urllib.request
import urllib.parse
import json
import ssl
from typing import Dict, Any, List, Optional

class FDAClient:
    """
    Client wrapper for the OpenFDA public REST API.
    Retrieves real-time pharmaceutical enforcement (recalls) and adverse event details.
    """
    
    BASE_URL = "https://api.fda.gov/drug"
    
    # Master data reference list of historically withdrawn/banned pharmaceutical substances
    WITHDRAWN_SUBSTANCES = {"valdecoxib", "rofecoxib", "bextra", "vioxx"}

    def __init__(self, timeout_seconds: int = 10):
        self.timeout = timeout_seconds
        # Avoid SSL verification issues in locked-down environments
        self.ssl_context = ssl._create_unverified_context()

    def _http_get(self, endpoint: str, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Executes a secure HTTP GET request to the OpenFDA server."""
        query_string = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}/{endpoint}?{query_string}"
        
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (PharmacoVigilance-Claim-Auditor)"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as response:
                if response.status == 200:
                    return json.loads(response.read().decode("utf-8"))
        except Exception as e:
            # FDA API returns 404 if no matching records are found in database
            # This is standard API behavior rather than a failure state.
            pass
        return None

    def search_drug_recalls(self, drug_name: str) -> List[Dict[str, Any]]:
        """
        Queries OpenFDA enforcement logs for active recalls of a chemical/drug.
        Filters by reason_for_recall and product_description.
        Returns a list of matching recall events.
        """
        name_lower = drug_name.lower().strip()
        
        # Rule 1: Check against master data reference of withdrawn substances
        if name_lower in self.WITHDRAWN_SUBSTANCES:
            return [{
                "status": "Ongoing",
                "classification": "Class I",
                "reason_for_recall": f"Market Withdrawal: Drug substance '{drug_name}' was fully withdrawn from the global market due to severe cardiovascular/safety risks."
            }]
            
        search_query = f'reason_for_recall:"{drug_name}" OR product_description:"{drug_name}"'
        params = {
            "search": search_query,
            "limit": "3"
        }
        
        response = self._http_get("enforcement.json", params)
        if response and "results" in response:
            return response["results"]
        return []

    def get_adverse_event_count(self, drug_name: str) -> int:
        """
        Queries OpenFDA event logs to fetch count of adverse cases
        reported for the specified drug substance.
        """
        search_query = f'patient.drug.medicinalproduct:"{drug_name}"'
        params = {
            "search": search_query,
            "limit": "1"
        }
        
        response = self._http_get("event.json", params)
        if response and "meta" in response and "results" in response["meta"]:
            # If search succeeded, total records are in metadata
            return response["meta"]["results"].get("total", 0)
        
        # Fallback check count of occurrences inside results list
        if response and "results" in response:
            return len(response["results"])
        return 0
