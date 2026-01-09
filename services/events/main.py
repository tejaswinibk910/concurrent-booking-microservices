from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from jose import JWTError, jwt
import sys
import os

# Add shared directory to path
sys.path.insert(0, '/app')

from shared.database.database import get_db, engine, Base
from shared.database.models import Event, Seat, SeatStatus, User, UserRole
from image_fetcher import fetch_event_image

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Events Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT settings
SECRET_KEY = os.getenv("JWT_SECRET", "supersecretkey-change-in-production-12345")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8000/login")

# Pydantic models
class EventCreate(BaseModel):
    name: str
    event_type: Optional[str] = None  # "movie" or "concert" (optional - will auto-detect)
    venue: str
    start_time: datetime
    end_time: datetime
    total_seats: int

class EventResponse(BaseModel):
    id: int
    name: str
    event_type: str
    venue: str
    start_time: datetime
    end_time: datetime
    created_at: datetime
    total_seats: int
    available_seats: int
    image_url: Optional[str] = None
    
    class Config:
        from_attributes = True

class SeatResponse(BaseModel):
    id: int
    seat_number: str
    status: str
    
    class Config:
        from_attributes = True

# Helper functions
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

async def require_admin(current_user: User = Depends(get_current_user)):
    """Require admin role for protected routes"""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

def generate_movie_seats(event_id: int, total_seats: int, db: Session):
    """
    Generate theater seating based on total_seats
    Uses standard theater layout: rows + numbered seats
    """
    seats = []
    
    # Calculate rows needed (assume ~15 seats per row)
    seats_per_row = 15
    num_rows = (total_seats + seats_per_row - 1) // seats_per_row  # Ceiling division
    
    rows = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:num_rows]
    
    for row_idx, row in enumerate(rows):
        # Last row might have fewer seats
        if row_idx == len(rows) - 1:
            remaining = total_seats - (row_idx * seats_per_row)
            seats_in_this_row = remaining
        else:
            seats_in_this_row = seats_per_row
        
        for seat_num in range(1, seats_in_this_row + 1):
            seat = Seat(
                event_id=event_id,
                seat_number=f"{row}{seat_num}",
                status=SeatStatus.available
            )
            seats.append(seat)
    
    db.bulk_save_objects(seats)
    db.commit()
    return len(seats)

def generate_concert_seats(event_id: int, total_seats: int, db: Session):
    """
    Generate concert seating based on total_seats
    Distributes across VIP (10%), GA (60%), Balcony (30%)
    """
    seats = []
    
    # Calculate distribution
    vip_count = int(total_seats * 0.10)
    ga_count = int(total_seats * 0.60)
    balcony_count = total_seats - vip_count - ga_count  # Remaining goes to balcony
    
    # VIP Section
    for i in range(1, vip_count + 1):
        seats.append(Seat(
            event_id=event_id,
            seat_number=f"VIP-{i}",
            status=SeatStatus.available
        ))
    
    # General Admission
    for i in range(1, ga_count + 1):
        seats.append(Seat(
            event_id=event_id,
            seat_number=f"GA-{i}",
            status=SeatStatus.available
        ))
    
    # Balcony
    for i in range(1, balcony_count + 1):
        seats.append(Seat(
            event_id=event_id,
            seat_number=f"BAL-{i}",
            status=SeatStatus.available
        ))
    
    db.bulk_save_objects(seats)
    db.commit()
    return len(seats)

# Routes
@app.get("/")
def root():
    return {"message": "Events Service API", "version": "1.0.0"}

@app.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    event: EventCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new movie or concert event with automatic image fetching (Admin only)"""
    
    # Fetch image automatically and detect event type
    image_url, detected_type = fetch_event_image(event.name, event.event_type)
    
    # Use detected type if not provided
    final_event_type = event.event_type or detected_type
    
    # Validate event type
    if final_event_type not in ["movie", "concert"]:
        raise HTTPException(status_code=400, detail="Event type must be 'movie' or 'concert'")
    
    # Validate seat count
    if event.total_seats < 10 or event.total_seats > 100000:
        raise HTTPException(status_code=400, detail="Total seats must be between 10 and 100,000")
    
    print(f"[INFO] Creating event: {event.name}")
    print(f"[INFO] Event type: {final_event_type}")
    print(f"[INFO] Image URL: {image_url}")
    
    # Create event with image URL and event type
    new_event = Event(
        name=event.name,
        venue=event.venue,
        start_time=event.start_time,
        end_time=event.end_time,
        image_url=image_url,
        event_type=final_event_type
    )
    db.add(new_event)
    db.commit()
    db.refresh(new_event)
    
    # Generate seats based on event type
    if final_event_type == "movie":
        total_seats = generate_movie_seats(new_event.id, event.total_seats, db)
    else:  # concert
        total_seats = generate_concert_seats(new_event.id, event.total_seats, db)
    
    return EventResponse(
        id=new_event.id,
        name=new_event.name,
        event_type=final_event_type,
        venue=new_event.venue,
        start_time=new_event.start_time,
        end_time=new_event.end_time,
        created_at=new_event.created_at,
        total_seats=total_seats,
        available_seats=total_seats,
        image_url=image_url
    )

@app.get("/events", response_model=List[EventResponse])
def list_events(db: Session = Depends(get_db)):
    """Get all events with images (Public - no auth required)"""
    events = db.query(Event).all()
    
    result = []
    for event in events:
        total = db.query(Seat).filter(Seat.event_id == event.id).count()
        available = db.query(Seat).filter(
            Seat.event_id == event.id,
            Seat.status == SeatStatus.available
        ).count()
        
        # Use stored event_type, fallback to detection if not set
        event_type = event.event_type
        if not event_type:
            first_seat = db.query(Seat).filter(Seat.event_id == event.id).first()
            event_type = "concert" if first_seat and "VIP" in first_seat.seat_number else "movie"
        
        result.append(EventResponse(
            id=event.id,
            name=event.name,
            event_type=event_type,
            venue=event.venue,
            start_time=event.start_time,
            end_time=event.end_time,
            created_at=event.created_at,
            total_seats=total,
            available_seats=available,
            image_url=event.image_url
        ))
    
    return result

@app.get("/events/browse")
def get_events_for_browse(db: Session = Depends(get_db)):
    """
    Lightweight endpoint for browse page - no seat counting
    Returns unique movies + all concerts
    """
    events = db.query(Event).all()
    
    # Get unique movies (first occurrence of each)
    seen_movies = set()
    unique_movies = []
    concerts = []
    
    for event in events:
        if event.event_type == 'movie':
            if event.name not in seen_movies:
                seen_movies.add(event.name)
                unique_movies.append({
                    "id": event.id,
                    "name": event.name,
                    "event_type": "movie",
                    "image_url": event.image_url
                })
        else:  # concert
            # Count available seats for concerts
            available = db.query(Seat).filter(
                Seat.event_id == event.id,
                Seat.status == SeatStatus.available
            ).count()
            
            concerts.append({
                "id": event.id,
                "name": event.name,
                "venue": event.venue,
                "start_time": event.start_time.isoformat(),
                "event_type": "concert",
                "image_url": event.image_url,
                "available_seats": available
            })
    
    return {
        "movies": unique_movies,
        "concerts": concerts
    }

@app.get("/events/movie/{movie_name}/showtimes")
def get_movie_showtimes(movie_name: str, db: Session = Depends(get_db)):
    """
    Fast endpoint to get all showtimes for a specific movie
    """
    # Decode URL-encoded movie name
    from urllib.parse import unquote
    decoded_name = unquote(movie_name)
    
    showtimes = db.query(Event).filter(
        Event.name == decoded_name,
        Event.event_type == 'movie'
    ).all()
    
    if not showtimes:
        return []
    
    result = []
    for showtime in showtimes:
        total = db.query(Seat).filter(Seat.event_id == showtime.id).count()
        available = db.query(Seat).filter(
            Seat.event_id == showtime.id,
            Seat.status == SeatStatus.available
        ).count()
        
        result.append({
            "id": showtime.id,
            "venue": showtime.venue,
            "start_time": showtime.start_time.isoformat(),
            "total_seats": total,
            "available_seats": available,
            "image_url": showtime.image_url
        })
    
    return result

@app.get("/events/{event_id}", response_model=EventResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    """Get specific event details (Public - no auth required)"""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    total = db.query(Seat).filter(Seat.event_id == event.id).count()
    available = db.query(Seat).filter(
        Seat.event_id == event.id,
        Seat.status == SeatStatus.available
    ).count()
    
    # Use stored event_type, fallback to detection if not set
    event_type = event.event_type
    if not event_type:
        first_seat = db.query(Seat).filter(Seat.event_id == event.id).first()
        event_type = "concert" if first_seat and "VIP" in first_seat.seat_number else "movie"
    
    return EventResponse(
        id=event.id,
        name=event.name,
        event_type=event_type,
        venue=event.venue,
        start_time=event.start_time,
        end_time=event.end_time,
        created_at=event.created_at,
        total_seats=total,
        available_seats=available,
        image_url=event.image_url
    )

@app.get("/events/{event_id}/seats", response_model=List[SeatResponse])
def get_event_seats(event_id: int, db: Session = Depends(get_db)):
    """Get all seats for an event (Public - no auth required)"""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    seats = db.query(Seat).filter(Seat.event_id == event_id).all()
    return [
        SeatResponse(id=s.id, seat_number=s.seat_number, status=s.status.value)
        for s in seats
    ]

@app.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete an event (Admin only)"""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    # Delete associated seats first (cascade)
    db.query(Seat).filter(Seat.event_id == event_id).delete()
    
    # Delete event
    db.delete(event)
    db.commit()
    
    return None

@app.get("/health")
def health_check():
    return {"status": "healthy"}