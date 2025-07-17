from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import asyncio
import time
import os
import random
import spacy
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

# Local imports
from database import SessionLocal, engine
from models import Base, User, Conversation

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Initialize NLP model
nlp = spacy.load("en_core_web_sm")

# Initialize FastAPI
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create database tables
Base.metadata.create_all(bind=engine)

# Request models
class PromptRequest(BaseModel):
    prompt: str
    user_id: int = 1  # Temporary until auth is implemented

class UserCreate(BaseModel):
    name: str
    email: str
    job_role: Optional[str] = None

# AI Model configuration
class AIModel:
    def __init__(self, name, model_id):
        self.name = name
        self.model_id = model_id

models = [
    AIModel("ChatGPT", "gpt-3.5-turbo"),
    AIModel("Gemini", "google/gemini-pro"),
    AIModel("DeepSeek", "deepseek/deepseek-chat"),
    AIModel("Qwen", "qwen/qwen-plus"),
    AIModel("Llama 2", "meta-llama/llama-3-70b-instruct")
]

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def extract_context(prompt: str, db: Session, user_id: int):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        persistent_context = user.context if user and user.context else {}
        
        doc = nlp(prompt)
        entities = {ent.text: ent.label_ for ent in doc.ents}
        
        # Extract FRESH context from current prompt only
        new_context = {
            "entities": entities,
            "personal_info": {
                "name": extract_name(doc),
                "job_role": extract_job_role(doc)  # Only from current prompt
            },
            "last_prompt": prompt
        }
        
        # Merge with persistent context but don't carry forward previous job roles
        merged_context = {
            "personal_info": {
                "name": new_context["personal_info"]["name"] or persistent_context.get("personal_info", {}).get("name"),
                # Job role is NOT carried forward intentionally
                "job_role": new_context["personal_info"]["job_role"]
            },
            "entities": {**persistent_context.get("entities", {}), **new_context["entities"]}
        }
        
        # Update user context without forcing job role persistence
        if user:
            user.context = {
                "personal_info": {
                    "name": merged_context["personal_info"]["name"]
                },
                "entities": merged_context["entities"]
            }
            db.commit()
        
        return merged_context
    except Exception as e:
        print(f"Context error: {str(e)}")
        return {}
    
@app.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int, 
    db: Session = Depends(get_db)
):
    try:
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()
        
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        db.delete(conversation)
        db.commit()
        return {"status": "success", "message": "Conversation deleted"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

def extract_name(doc):
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            return ent.text
    return None

def extract_job_role(doc):
    job_keywords = ["engineer", "manager", "developer", "analyst", "researcher"]
    for token in doc:
        if token.text.lower() in job_keywords:
            return token.text
    return None

def parse_response(provider: str, response: dict):
    try:
        # Provider-specific response handling
        if provider == "ChatGPT":
            return response["choices"][0]["message"]["content"]
        elif provider == "Gemini":
            return response["candidates"][0]["content"]["parts"][0]["text"]
        elif provider == "DeepSeek":
            return response["choices"][0]["message"]["content"]
        elif provider == "Qwen":
            return response["output"]["text"]
        elif provider == "Llama 2":
            return response["generations"][0]["text"]
        return "Unexpected provider format"
    except KeyError as e:
        error_msg = f"Missing key {str(e)} in {provider} response"
        print(f"Parsing error: {error_msg}")
        return f"⚠️ API Format Error: {error_msg}"
    except IndexError as e:
        error_msg = f"Empty response array from {provider}"
        print(f"Parsing error: {error_msg}")
        return f"⚠️ Empty Response: {error_msg}"
    except Exception as e:
        error_msg = f"Unexpected error processing {provider} response: {str(e)}"
        print(error_msg)
        return f"⚠️ Processing Error: {error_msg}"

async def call_openrouter(model: AIModel, prompt: str, context: dict):
    start_time = time.time()
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_KEY')}",
        "HTTP-Referer": "https://your-domain.com",
        "X-Title": "AI Synthesis"
    }
    
    formatted_prompt = f"""Context: {context}
    
Please format your response using Markdown with:
- Clear section headers (##)
- Bullet points for lists
- Code blocks for examples (```)
- LaTeX for equations ($$)
- Tables for comparisons

Question: {prompt}"""

    for attempt in range(3):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": model.model_id,
                        "messages": [{"role": "user", "content": formatted_prompt}],
                        "temperature": 0.7
                    },
                    timeout=30
                )

                if response.status_code == 429:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                
                return {
                    "provider": model.name,
                    "content": response.json()["choices"][0]["message"]["content"],
                    "latency": int((time.time() - start_time) * 1000),
                    "success": True
                }

        except httpx.HTTPStatusError as e:
            error = f"HTTP error {e.response.status_code}"
            if e.response.status_code in [429, 503]:
                continue
            break
        except Exception as e:
            error = str(e)
            break

    return {
        "provider": model.name,
        "error": error or "Service unavailable",
        "latency": int((time.time() - start_time) * 1000),
        "success": False
    }

async def synthesize_responses(responses: list, context: dict):
    """Synthesizes multiple AI responses into a single, coherent answer.
    
    Parameters:
        responses (list): A list of dictionaries containing AI responses.
        context (dict): The context dictionary for the current conversation.
        
    Returns:
        dict: A dictionary with the synthesized response or an error message.
    """
    # Filter out responses that failed or don't contain content
    valid_responses = [r["content"] for r in responses if r.get("success") and "content" in r]
    if not valid_responses:
        return {"error": "All systems failed to respond"}
    
    # Construct a detailed synthesis prompt using prompt engineering
    synthesis_prompt = f"""Context: {context}
    
You are an advanced AI designed to merge responses from various AI systems into one comprehensive answer.
Below are responses from different models:
    
{chr(10).join(valid_responses)}
    
    ### Guidelines for Synthesis:
    1. **Technical Accuracy**: Maintain precise technical details from all sources
    2. **Conciseness**: Remove redundant information while preserving unique insights
    3. **Markdown Structure**:
       - Use ## for main section headers
       - Use bullet points for lists
       - Use ``` for code blocks
       - Use $$ for LaTeX equations
       - Use tables for comparisons
    4. **Highlight Conflicts**: Note any disagreements between sources
    5. **Code Examples**: Format code with appropriate syntax highlighting
    6. **Visual Hierarchy**: Ensure clear organization with proper spacing
    7. **Mathematical Clarity**: Use LaTeX for all mathematical expressions
    8. **Comparative Analysis**: Create tables for comparing different approaches
    9. **Response Quality**: Prioritize responses with lower latency
    10. **Source Reliability**: Weight responses based on provider reliability
    
    Now, generate a well-structured synthesis following these guidelines."""
    
    # Sort models by success rate and latency for optimal synthesis
    successful_models = [
        model for model in models
        if any(r["provider"] == model.name and r["success"] for r in responses)
    ]
    
    # Try models in order of reliability
    for model in successful_models:
        try:
            result = await call_openrouter(model, synthesis_prompt, context)
            if result.get("success"):
                return result
        except Exception as e:
            continue
    
    # Fallback to the first successful response if synthesis fails
    for response in responses:
        if response.get("success"):
            return {
                "provider": "Fallback",
                "content": response["content"],
                "latency": response["latency"],
                "success": True
            }
    
    return {"error": "Synthesis failed across all models"}

@app.post("/process")
async def process_prompt(request: PromptRequest, db: Session = Depends(get_db)):
    try:
        # Extract and update context
        context = extract_context(request.prompt, db, request.user_id)
        
        # Process prompt with context
        tasks = [call_openrouter(model, request.prompt, context) for model in models]
        responses = await asyncio.gather(*tasks)
        
        # Generate synthesis
        synthesis_result = await synthesize_responses(responses, context)
        
        # Store conversation
        conversation = Conversation(
            user_id=request.user_id,
            prompt=request.prompt,
            responses=responses,
            synthesis=synthesis_result.get("content", ""),
            context=context,
            created_at=datetime.utcnow()
        )
        db.add(conversation)
        db.commit()
        
        return {
            "conversation_id": conversation.id,
            "responses": responses,
            "synthesis": synthesis_result
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/conversations")
async def get_conversations(user_id: int, db: Session = Depends(get_db)):
    return db.query(Conversation).filter(
        Conversation.user_id == user_id
    ).order_by(Conversation.created_at.desc()).all()

@app.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int, 
    db: Session = Depends(get_db)
):
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return conversation

@app.post("/users")
async def create_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = User(
        name=user.name,
        email=user.email,
        job_role=user.job_role,
        created_at=datetime.utcnow()
    )
    db.add(db_user)
    db.commit()
    return db_user

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)