"""Mock translator for testing - adds [DE] prefix instead of real translation"""

class MockTranslator:
    def __init__(self):
        pass
    
    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Mock translation - just adds language prefix"""
        return f"[{target_lang.upper()}] {text[:500]}"
