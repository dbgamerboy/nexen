import requests
from qdrant_client import QdrantClient

# Connect to the Qdrant database we set up in the previous step
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
COLLECTION_NAME = "enterprise_knowledge"

class AgentTeamOrchestrator:
    def __init__(self):
        # Statically defined local ports for CPU servers (llama.cpp)
        # Running with -t 4 to leave the RTX 2070 completely untouched for gaming
        self.agents = {
            "parser": "http://localhost:8081",
            "router": "http://localhost:8082",
            "coder":  "http://localhost:8083",
            "linter": "http://localhost:8084"
        }

    def execute_agent_step(self, agent_name, context_packet, user_payload):
        print(f"--> Invoking Agent: [{agent_name.upper()}] on {self.agents[agent_name]}")
        full_prompt = f"<context>\n{context_packet}\n</context>\n\nTask: {user_payload}"
        
        try:
            response = requests.post(
                f"{self.agents[agent_name]}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": full_prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2048
                },
                timeout=120
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[ERROR] Failed to reach {agent_name} agent: {e}"

    def retrieve_context_from_qdrant(self, query: str):
        print("--> Querying Qdrant Vector Database for Context Packet...")
        # Placeholder dense vector - in production, embed the query first
        fake_vector = [0.0] * 384
        
        try:
            results = client.search(
                collection_name=COLLECTION_NAME,
                query_vector=("dense", fake_vector),
                limit=3
            )
            context = "\n".join([hit.payload.get("text_content", "") for hit in results])
            return context if context else "No additional context found."
        except Exception as e:
            return f"[ERROR] Failed to query Qdrant: {e}"

    def run_pipeline(self, user_request):
        # Step 1: Parser extracts intent
        intent_packet = "Format explicitly as JSON. Valid tags: [FIX, GEN, REFACTOR]"
        parsed_meta = self.execute_agent_step("parser", intent_packet, user_request)
        
        # Step 2: Router gets relevant code snippets from Qdrant
        db_context = self.retrieve_context_from_qdrant(parsed_meta)
        
        # Step 3: Heavyweight code engine builds the script
        generated_code = self.execute_agent_step("coder", db_context, parsed_meta)
        
        # Step 4: Linter validates
        lint_rules = "Check for unhandled exceptions and missing imports."
        final_code = self.execute_agent_step("linter", lint_rules, generated_code)
        
        return final_code

if __name__ == "__main__":
    orchestrator = AgentTeamOrchestrator()
    print("Agent Team Orchestrator Initialized.")
    print("Ready to process requests using Qdrant Context Packets and CPU-bound LLMs.")
