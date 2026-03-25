import requests

class LibreTranslateClient:
    def __init__(self, endpoint: str = "http://localhost:5000"):
        self.endpoint = endpoint
        self.timeout = 30
    
    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate using LibreTranslate API"""
        try:
            response = requests.post(
                f"{self.endpoint}/translate",
                json={
                    "q": text[:1000],  # Limit length
                    "source": source_lang,
                    "target": target_lang,
                    "format": "html"
                },
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json().get("translatedText", text)
            else:
                return None
        except Exception as e:
            print(f"LibreTranslate error: {e}")
            return None
