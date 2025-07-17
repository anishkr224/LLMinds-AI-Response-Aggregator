from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    email = Column(String(100), unique=True, index=True)
    job_role = Column(String(100))
    context = Column(JSON)  # Stores user preferences and context
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    prompt = Column(Text)
    responses = Column(JSON)  # Stores raw responses from AI providers
    synthesis = Column(Text)  # Final synthesized answer
    context = Column(JSON)    # Context used for this conversation
    created_at = Column(DateTime, default=datetime.utcnow)