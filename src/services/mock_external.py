"""
Mock External Service
---------------------
Simulates an external dependency (e.g., a Credit Bureau API or Document Verification Service).

In production, replace this with actual HTTP calls.
The failure simulation demonstrates retry and resilience logic.
"""
import random
from typing import Dict, Any


class ExternalServiceError(Exception):
    """Raised when the external service fails (network error, timeout, 5xx)."""
    pass


class MockCreditBureauService:
    """
    Simulates a credit bureau API that verifies applicant credit data.
    
    Behaviour:
    - 80% success rate normally
    - Can be forced to fail by setting force_failure=True
    - Returns enriched credit data on success
    """

    def __init__(self, failure_rate: float = 0.2, force_failure: bool = False):
        self.failure_rate  = failure_rate
        self.force_failure = force_failure

    def verify(self, applicant_id: str, declared_credit_score: int) -> Dict[str, Any]:
        """
        Verify an applicant's credit score against bureau records.
        Returns verified data or raises ExternalServiceError.
        """
        if self.force_failure or random.random() < self.failure_rate:
            raise ExternalServiceError(
                f"Credit bureau unavailable for applicant '{applicant_id}' (simulated failure)"
            )

        # Simulate slight discrepancy between declared and bureau score (±20 pts)
        bureau_score = declared_credit_score + random.randint(-20, 20)
        bureau_score = max(300, min(850, bureau_score))

        return {
            "applicant_id":   applicant_id,
            "bureau_score":   bureau_score,
            "declared_score": declared_credit_score,
            "discrepancy":    abs(bureau_score - declared_credit_score),
            "risk_flag":      bureau_score < 580,
            "verified":       True,
        }


class MockDocumentVerificationService:
    """
    Simulates a document verification API.
    Returns document authenticity status.
    """

    def __init__(self, failure_rate: float = 0.15, force_failure: bool = False):
        self.failure_rate  = failure_rate
        self.force_failure = force_failure

    def verify(self, applicant_id: str, document_types: list) -> Dict[str, Any]:
        if self.force_failure or random.random() < self.failure_rate:
            raise ExternalServiceError(
                f"Document verification service unavailable (simulated failure)"
            )

        results = {}
        for doc in document_types:
            # 90% docs pass verification
            results[doc] = random.random() > 0.1

        all_passed = all(results.values())
        return {
            "applicant_id":    applicant_id,
            "document_results": results,
            "all_verified":    all_passed,
            "failed_documents": [d for d, ok in results.items() if not ok],
        }


# Registry: maps service name (from config) to class
SERVICE_REGISTRY = {
    "credit_bureau":          MockCreditBureauService,
    "document_verification":  MockDocumentVerificationService,
}


def get_service(service_name: str, **kwargs):
    """Factory: get a service instance by name from config."""
    cls = SERVICE_REGISTRY.get(service_name)
    if not cls:
        raise ValueError(f"Unknown external service: '{service_name}'. "
                         f"Available: {list(SERVICE_REGISTRY.keys())}")
    return cls(**kwargs)
