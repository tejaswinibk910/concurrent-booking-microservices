from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from .database import Base

class UserRole(enum.Enum):
    admin = "admin"
    user = "user"

class SeatStatus(enum.Enum):
    available = "available"
    held = "held"
    booked = "booked"

class BookingStatus(enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.user, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    bookings = relationship("Booking", back_populates="user")

class Event(Base):
    __tablename__ = "events"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    venue = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    image_url = Column(Text, nullable=True)  # NEW FIELD
    event_type = Column(String, nullable=True)  # NEW FIELD: 'movie' or 'concert'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    seats = relationship("Seat", back_populates="event")
    bookings = relationship("Booking", back_populates="event")

class Seat(Base):
    __tablename__ = "seats"
    
    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    seat_number = Column(String, nullable=False)
    status = Column(Enum(SeatStatus), default=SeatStatus.available, nullable=False)
    hold_expiry = Column(DateTime, nullable=True)
    
    event = relationship("Event", back_populates="seats")
    bookings = relationship("Booking", back_populates="seat")

class Booking(Base):
    __tablename__ = "bookings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    seat_id = Column(Integer, ForeignKey("seats.id"), nullable=False)
    status = Column(Enum(BookingStatus), default=BookingStatus.pending, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="bookings")
    event = relationship("Event", back_populates="bookings")
    seat = relationship("Seat", back_populates="bookings")