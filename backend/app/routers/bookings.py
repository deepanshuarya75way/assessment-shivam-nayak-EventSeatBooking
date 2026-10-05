import asyncio
import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas, auth
from app.database import get_db, SessionLocal
from app.redis_client import redis_client, seat_lock_key
from app.websocket_manager import manager


router = APIRouter(prefix="/bookings", tags=["bookings"])


async def process_booking(operation_id: str):
    db=SessionLocal()

    try:
        operation=(
            db.query(models.BookingOperation).filter(
                models.BookingOperation.operation_id == operation_id).first()

        )
            if not operation: 
                    return
            booking = models.Booking(
                    seat_id=operation.seat_id,
                    event_id=operation.event_id,
                    user_id=operation.user_id,
                )
            db.add(booking)
            db.commit()
            db.refresh(booking)

            operation.status="confirmed"
            operation.booking_id=booking.id
            db.commit()

            key = seat_local_key(operation.seat_id)
            redis_client.delete(key)

                await manager.broadcast(
                    operation.event_id,
                    {
                        "type: "seat_booked",
                        "seat_id":operation.seat_id,
                    },
                )

                except Exception as exc: 
                    db.rollback()

                    operation=(
                        db.query(models.BookingOperation).filter(
                            models.models.BookingOperation.operation_id == operation_id).first()
                        )
                           
                        if operation:
                            operation.status="failed"

                            operation.error_message=str(exc)

                            db.commit()

    finally:
          db.close()
                    


            
        

@router.post(
     "",
    responce_model=schemas.BookingOperationnOut, status_code=status.HTTP_202_ACCEPTED,


)



async def create_booking(
    payload: schemas.BookingCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    seat = db.query(models.Seat).filter(models.Seat.id == payload.seat_id).first()
    if not seat:
        raise HTTPException(status_code=404, detail="Seat not found")

    key = seat_lock_key(seat.id)
    owner = redis_client.get(key)
    if owner != str(current_user.id):
        raise HTTPException(
            status_code=409,
            detail="You must hold an active lock on this seat before confirming it "
                   "(your hold may have expired — try selecting the seat again).",
        )


    operation = models.BookingOperation(
        operations_id=payload.operation_id,
        seat_id=seat.id,
        event_id=seat.event_id,
        users_id=current_user.id,
        status="pending",
        attempt_count=0,

      next_attempt_st=datetime.datetime.utcnow(),
    )

    db.add(operation)
    db.commit()
    db.refresh(operation)

    asyncio.create_task(
        process_booking_operation(operation.operation_id)
    )

    return operation

    booking = models.Booking(seat_id=seat.id, event_id=seat.event_id, user_id=current_user.id)
    db.add(booking)
    try:
        db.commit()
    except IntegrityError:
        
        db.rollback()
        raise HTTPException(status_code=409, detail="Seat was just booked by someone else")

    db.refresh(booking)
    redis_client.delete(key)

    await manager.broadcast(seat.event_id, {"type": "seat_booked", "seat_id": seat.id})
    return booking


@router.get("/me", response_model=list[schemas.BookingOut])
def my_bookings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return (
        db.query(models.Booking)
        .filter(models.Booking.user_id == current_user.id)
        .order_by(models.Booking.booked_at.desc())
        .all()
    )
