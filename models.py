from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    encrypted_jira_info = Column(Text, nullable=True)  # Store encrypted JSON blob
    crypto_salt = Column(String(255), nullable=True)  # Salt for PBKDF2
    
    # Relationship to configurations
    configurations = relationship("Configuration", back_populates="user", cascade="all, delete-orphan")

class Configuration(Base):
    __tablename__ = 'configurations'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    name = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)  # JSON string of config values

    # Relationship to user
    user = relationship("User", back_populates="configurations")

engine = create_engine('sqlite:///jira_clone.db')
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
