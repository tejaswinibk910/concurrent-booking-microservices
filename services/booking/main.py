from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Dict, Set, Any
from pydantic import BaseModel
from jose import JWTError, jwt
from contextlib import asynccontextmanager
import asyncio
import json
import sys
import os

# Add shared directory to path
sys.path.insert(0, '/app')

from shared.database.database import get_db, engine, Base
from shared.database.models import Event, Seat, SeatStatus, User, Booking, BookingStatus
from shared.redis.redis_client import get_redis

# Create tables
Base.metadata.create_all(bind=engine)

# JWT settings
SECRET_KEY = os.getenv("JWT_SECRET", "supersecretkey-change-in-production-12345")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8000/login")

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, event_id: int):
        await websocket.accept()
        if event_id not in self.active_connections:
            self.active_connections[event_id] = set()
        self.active_connections[event_id].add(websocket)

    def disconnect(self, websocket: WebSocket, event_id: int):
        if event_id in self.active_connections:
            self.active_connections[event_id].discard(websocket)
            if not self.active_connections[event_id]:
                del self.active_connections[event_id]

    async def broadcast_to_event(self, event_id: int, message: dict):
        if event_id in self.active_connections:
            disconnected = set()
            for connection in self.active_connections[event_id]:
                try:
                    await connection.send_json(message)
                except:
                    disconnected.add(connection)
            
            for conn in disconnected:
                self.active_connections[event_id].discard(conn)

manager = ConnectionManager()

# Background task to clean up expired seat holds
async def cleanup_expired_holds():
    while True:
        try:
            await asyncio.sleep(10)  # ✅ Changed from 60 to 10 seconds
            
            db_gen = get_db()
            db = next(db_gen)
            redis = get_redis()
            
            try:
                now = datetime.utcnow()
                expired_seats = db.query(Seat).filter(
                    Seat.status == SeatStatus.held,
                    Seat.hold_expiry < now
                ).all()
                
                for seat in expired_seats:
                    lock_key = f"seat_lock:{seat.id}"
                    if not redis.exists(lock_key):
                        seat.status = SeatStatus.available
                        seat.hold_expiry = None
                        
                        await manager.broadcast_to_event(seat.event_id, {
                            "type": "seat_update",
                            "seat_id": seat.id,
                            "seat_number": seat.seat_number,
                            "status": "available"
                        })
                        
                        print(f"[EXPIRY] Released seat {seat.seat_number} (ID: {seat.id})")
                
                if expired_seats:
                    db.commit()
                    print(f"[EXPIRY] Cleaned up {len(expired_seats)} expired seat holds")
                    
            finally:
                db.close()
                
        except Exception as e:
            print(f"[EXPIRY ERROR] {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup_expired_holds())
    print("[STARTUP] Background expiry task started")
    yield
    task.cancel()
    print("[SHUTDOWN] Background expiry task stopped")

app = FastAPI(title="Booking Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class SeatHoldRequest(BaseModel):
    event_id: int
    seat_id: int

class MultiSeatHoldRequest(BaseModel):
    event_id: int
    seat_ids: List[int]

class SeatHoldResponse(BaseModel):
    success: bool
    message: str
    seat_id: int
    hold_expires_at: str | None = None  # ✅ FIXED: Changed from datetime to string

class MultiSeatHoldResponse(BaseModel):
    success: bool
    message: str
    held_seats: List[int]
    failed_seats: List[Dict[str, Any]]
    hold_expires_at: str | None = None  # ✅ FIXED: Changed from datetime to string

class BookingConfirmRequest(BaseModel):
    seat_ids: List[int]

class BookingResponse(BaseModel):
    id: int
    user_id: int
    event_id: int
    seat_id: int
    seat_number: str
    status: str
    created_at: datetime
    
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

# Routes
@app.get("/")
def root():
    return {"message": "Booking Service API", "version": "1.0.0"}

@app.post("/hold", response_model=SeatHoldResponse)
async def hold_seat(
    request: SeatHoldRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Hold a single seat (legacy endpoint - use /hold-multiple for better UX)"""
    redis = get_redis()
    
    seat = db.query(Seat).filter(Seat.id == request.seat_id).first()
    if not seat:
        raise HTTPException(status_code=404, detail="Seat not found")
    
    if seat.event_id != request.event_id:
        raise HTTPException(status_code=400, detail="Seat does not belong to this event")
    
    lock_key = f"seat_lock:{request.seat_id}"
    lock_acquired = redis.set(lock_key, current_user.id, nx=True, ex=300)
    
    if not lock_acquired:
        lock_holder = redis.get(lock_key)
        if lock_holder and int(lock_holder) == current_user.id:
            ttl = redis.ttl(lock_key)
            expiry = datetime.utcnow() + timedelta(seconds=ttl)
            return SeatHoldResponse(
                success=True,
                message="You already have this seat on hold",
                seat_id=request.seat_id,
                hold_expires_at=expiry.strftime('%Y-%m-%dT%H:%M:%SZ')  # ✅ FIXED: UTC format
            )
        else:
            return SeatHoldResponse(
                success=False,
                message="This seat is currently held by another user",
                seat_id=request.seat_id
            )
    
    seat.status = SeatStatus.held
    seat.hold_expiry = datetime.utcnow() + timedelta(minutes=5)
    db.commit()
    
    await manager.broadcast_to_event(request.event_id, {
        "type": "seat_update",
        "seat_id": request.seat_id,
        "seat_number": seat.seat_number,
        "status": "held",
        "user_id": current_user.id
    })
    
    return SeatHoldResponse(
        success=True,
        message="Seat successfully held for 5 minutes",
        seat_id=request.seat_id,
        hold_expires_at=seat.hold_expiry.strftime('%Y-%m-%dT%H:%M:%SZ')  # ✅ FIXED: UTC format
    )

@app.post("/hold-multiple", response_model=MultiSeatHoldResponse)
async def hold_multiple_seats(
    request: MultiSeatHoldRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Hold multiple seats atomically - all-or-nothing approach.
    If any seat cannot be locked, all locks are released.
    """
    redis = get_redis()
    
    if not request.seat_ids:
        raise HTTPException(status_code=400, detail="No seats provided")
    
    if len(request.seat_ids) > 10:
        raise HTTPException(status_code=400, detail="Cannot hold more than 10 seats at once")
    
    # Fetch all seats
    seats = db.query(Seat).filter(Seat.id.in_(request.seat_ids)).all()
    
    if len(seats) != len(request.seat_ids):
        raise HTTPException(status_code=404, detail="One or more seats not found")
    
    # Verify all seats belong to the same event
    event_ids = set(seat.event_id for seat in seats)
    if len(event_ids) > 1:
        raise HTTPException(status_code=400, detail="All seats must belong to the same event")
    
    if request.event_id not in event_ids:
        raise HTTPException(status_code=400, detail="Seats do not belong to specified event")
    
    # Try to acquire all locks
    acquired_locks = []
    failed_seats = []
    
    for seat in seats:
        lock_key = f"seat_lock:{seat.id}"
        lock_acquired = redis.set(lock_key, current_user.id, nx=True, ex=300)
        
        if lock_acquired:
            acquired_locks.append(seat.id)
        else:
            # Check if user already owns this lock
            lock_holder = redis.get(lock_key)
            if lock_holder and int(lock_holder) == current_user.id:
                acquired_locks.append(seat.id)
            else:
                failed_seats.append({
                    "seat_id": seat.id,
                    "seat_number": seat.seat_number,
                    "reason": "Already held by another user"
                })
    
    # If any seat failed, release all acquired locks (rollback)
    if failed_seats:
        for seat_id in acquired_locks:
            lock_key = f"seat_lock:{seat_id}"
            # Only delete if we just acquired it (not pre-existing user lock)
            if seat_id not in [s["seat_id"] for s in failed_seats]:
                redis.delete(lock_key)
        
        return MultiSeatHoldResponse(
            success=False,
            message=f"Failed to hold {len(failed_seats)} seat(s). All locks released.",
            held_seats=[],
            failed_seats=failed_seats
        )
    
    # All locks acquired! Update database
    hold_expiry = datetime.utcnow() + timedelta(minutes=5)
    
    for seat in seats:
        seat.status = SeatStatus.held
        seat.hold_expiry = hold_expiry
    
    db.commit()
    
    # Broadcast updates for all seats
    for seat in seats:
        await manager.broadcast_to_event(request.event_id, {
            "type": "seat_update",
            "seat_id": seat.id,
            "seat_number": seat.seat_number,
            "status": "held",
            "user_id": current_user.id
        })
    
    return MultiSeatHoldResponse(
        success=True,
        message=f"Successfully held {len(acquired_locks)} seat(s) for 5 minutes",
        held_seats=acquired_locks,
        failed_seats=[],
        hold_expires_at=hold_expiry.strftime('%Y-%m-%dT%H:%M:%SZ')  # ✅ FIXED: UTC format
    )

@app.post("/confirm")
async def confirm_booking(
    request: BookingConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Confirm booking for multiple seats"""
    redis = get_redis()
    
    if not request.seat_ids:
        raise HTTPException(status_code=400, detail="No seats provided")
    
    confirmed_bookings = []
    failed_seats = []
    
    for seat_id in request.seat_ids:
        lock_key = f"seat_lock:{seat_id}"
        lock_holder = redis.get(lock_key)
        
        if not lock_holder or int(lock_holder) != current_user.id:
            failed_seats.append(seat_id)
            continue
        
        seat = db.query(Seat).filter(Seat.id == seat_id).first()
        if not seat:
            failed_seats.append(seat_id)
            continue
        
        # Update seat to booked
        seat.status = SeatStatus.booked
        seat.hold_expiry = None
        
        # Create booking record
        booking = Booking(
            user_id=current_user.id,
            event_id=seat.event_id,
            seat_id=seat.id,
            status=BookingStatus.confirmed
        )
        db.add(booking)
        confirmed_bookings.append(seat)
        
        # Release Redis lock
        redis.delete(lock_key)
    
    db.commit()
    
    # Broadcast updates
    for seat in confirmed_bookings:
        await manager.broadcast_to_event(seat.event_id, {
            "type": "seat_update",
            "seat_id": seat.id,
            "seat_number": seat.seat_number,
            "status": "booked",
            "user_id": current_user.id
        })
    
    if failed_seats:
        return {
            "success": False,
            "message": f"Confirmed {len(confirmed_bookings)} seat(s), failed {len(failed_seats)}",
            "confirmed_seats": [s.id for s in confirmed_bookings],
            "failed_seats": failed_seats
        }
    
    return {
        "success": True,
        "message": f"Successfully confirmed {len(confirmed_bookings)} booking(s)",
        "confirmed_seats": [s.id for s in confirmed_bookings]
    }

@app.post("/release")
async def release_seats(
    seat_ids: List[int],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Release multiple held seats"""
    redis = get_redis()
    
    released_seats = []
    failed_seats = []
    
    for seat_id in seat_ids:
        lock_key = f"seat_lock:{seat_id}"
        lock_holder = redis.get(lock_key)
        
        if not lock_holder or int(lock_holder) != current_user.id:
            failed_seats.append(seat_id)
            continue
        
        seat = db.query(Seat).filter(Seat.id == seat_id).first()
        if not seat:
            failed_seats.append(seat_id)
            continue
        
        seat.status = SeatStatus.available
        seat.hold_expiry = None
        released_seats.append(seat)
        
        redis.delete(lock_key)
    
    db.commit()
    
    # Broadcast updates
    for seat in released_seats:
        await manager.broadcast_to_event(seat.event_id, {
            "type": "seat_update",
            "seat_id": seat.id,
            "seat_number": seat.seat_number,
            "status": "available"
        })
    
    return {
        "success": True,
        "message": f"Released {len(released_seats)} seat(s)",
        "released_seats": [s.id for s in released_seats],
        "failed_seats": failed_seats
    }

@app.post("/cancel-booking/{booking_id}")
async def cancel_booking(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a confirmed booking and free up the seat"""
    # Get booking
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.user_id == current_user.id
    ).first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    if booking.status == BookingStatus.cancelled:
        raise HTTPException(status_code=400, detail="Booking already cancelled")
    
    # Get seat
    seat = db.query(Seat).filter(Seat.id == booking.seat_id).first()
    if not seat:
        raise HTTPException(status_code=404, detail="Seat not found")
    
    # Update booking status
    booking.status = BookingStatus.cancelled
    
    # Free up the seat
    seat.status = SeatStatus.available
    seat.hold_expiry = None
    
    db.commit()
    
    # Broadcast seat availability
    await manager.broadcast_to_event(seat.event_id, {
        "type": "seat_update",
        "seat_id": seat.id,
        "seat_number": seat.seat_number,
        "status": "available"
    })
    
    return {
        "success": True,
        "message": "Booking cancelled successfully",
        "booking_id": booking_id
    }

@app.get("/my-holds/{event_id}")
async def get_my_holds(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all seats currently held by this user for an event"""
    redis = get_redis()
    
    # Get all seats for this event that are held
    seats = db.query(Seat).filter(
        Seat.event_id == event_id,
        Seat.status == SeatStatus.held
    ).all()
    
    my_held_seats = []
    hold_expiry = None
    
    for seat in seats:
        lock_key = f"seat_lock:{seat.id}"
        lock_holder = redis.get(lock_key)
        
        # Check if this seat is held by current user
        if lock_holder and int(lock_holder) == current_user.id:
            ttl = redis.ttl(lock_key)
            
            # Calculate expiry time
            if ttl > 0:
                expiry = datetime.utcnow() + timedelta(seconds=ttl)
                if not hold_expiry or expiry < hold_expiry:
                    hold_expiry = expiry  # Use earliest expiry
            
            my_held_seats.append({
                "seat_id": seat.id,
                "seat_number": seat.seat_number,
                "expires_in_seconds": ttl
            })
    
    return {
        "event_id": event_id,
        "held_seats": my_held_seats,
        # ✅ FIXED: UTC format with Z suffix
        "hold_expires_at": hold_expiry.strftime('%Y-%m-%dT%H:%M:%SZ') if hold_expiry else None
    }

@app.get("/my-bookings", response_model=List[BookingResponse])
def get_my_bookings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    bookings = db.query(Booking).filter(Booking.user_id == current_user.id).all()
    
    results = []
    for booking in bookings:
        seat = db.query(Seat).filter(Seat.id == booking.seat_id).first()
        results.append(BookingResponse(
            id=booking.id,
            user_id=booking.user_id,
            event_id=booking.event_id,
            seat_id=booking.seat_id,
            seat_number=seat.seat_number if seat else "Unknown",
            status=booking.status.value,
            created_at=booking.created_at
        ))
    
    return results

@app.get("/events/{event_id}/seats/fast")
def get_seats_fast(event_id: int, db: Session = Depends(get_db)):
    """Ultra-fast REST endpoint to get all seats for an event"""
    seats = db.query(Seat).filter(Seat.event_id == event_id).all()
    
    return {
        "event_id": event_id,
        "seats": [
            {
                "id": s.id,
                "seat_number": s.seat_number,
                "status": s.status.value
            }
            for s in seats
        ]
    }

@app.websocket("/ws/events/{event_id}")
async def websocket_endpoint(websocket: WebSocket, event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        await websocket.close(code=1008, reason="Event not found")
        return
    
    await manager.connect(websocket, event_id)
    
    try:
        seats = db.query(Seat).filter(Seat.event_id == event_id).all()
        initial_data = {
            "type": "initial",
            "event_id": event_id,
            "event_name": event.name,
            "seats": [
                {
                    "id": seat.id,
                    "seat_number": seat.seat_number,
                    "status": seat.status.value
                }
                for seat in seats
            ]
        }
        await websocket.send_json(initial_data)
        
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({"type": "pong"})
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, event_id)

@app.get("/health")
def health_check():
    return {"status": "healthy"}