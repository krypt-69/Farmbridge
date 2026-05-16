import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.user import User, UserRole
from app.models.shipment import Shipment, ShipmentStatus
from app.models.order import Order, OrderStatus
from app.models.verification import VerificationReport, VerificationStatus
from app.models.harvest import Harvest, HarvestStatus
from app.models.rating import Rating
from app.models.feedback import Feedback, FeedbackType   # <-- added import
from datetime import datetime, timezone

async def recalc_farmer_rating(db: AsyncSession, farmer_id: uuid.UUID) -> Rating:
    """Calculate rating for a farmer based on:
       - Agent verification accuracy (40%)
       - Delivery consistency (40%) – from completed shipments
       - Platform efficiency (20%) – number of successful harvests vs total
    """
    # 1. Agent verification accuracy: average (actual_quantity / claimed_quantity) across verifications for this farmer
    verifications = (await db.execute(
        select(VerificationReport).where(
            VerificationReport.farmer_id == farmer_id,
            VerificationReport.status.in_([VerificationStatus.APPROVED, VerificationStatus.ADJUSTED]),
        )
    )).scalars().all()

    accuracy_sum = 0.0
    accuracy_count = 0
    for v in verifications:
        if v.claimed_quantity_bags and v.actual_quantity_bags:
            if v.claimed_quantity_bags > 0:
                accuracy_sum += min(v.actual_quantity_bags / v.claimed_quantity_bags, 1.0)
                accuracy_count += 1
    agent_accuracy = (accuracy_sum / accuracy_count) if accuracy_count > 0 else 1.0

    # 2. Delivery consistency: ratio of harvests that reached DELIVERED state vs total matched harvests
    harvests = (await db.execute(
        select(Harvest).where(Harvest.farmer_id == farmer_id)
    )).scalars().all()
    total_harvests = len(harvests)
    delivered_harvests = 0
    for h in harvests:
        if h.shipment_id:
            shipment = (await db.execute(select(Shipment).where(Shipment.id == h.shipment_id))).scalar_one_or_none()
            if shipment and shipment.status == ShipmentStatus.DELIVERED:
                delivered_harvests += 1
    delivery_ratio = (delivered_harvests / total_harvests) if total_harvests > 0 else 0.5

    # 3. Platform efficiency: ratio of harvests that became VERIFIED or beyond vs total
    active_harvests = sum(1 for h in harvests if h.status in (HarvestStatus.MATCHED, HarvestStatus.VERIFIED, HarvestStatus.CANCELLED))
    efficiency_ratio = (active_harvests / total_harvests) if total_harvests > 0 else 0.5

    # Weighted score (scale 1.0–5.0)
    score = (0.4 * agent_accuracy + 0.4 * delivery_ratio + 0.2 * efficiency_ratio) * 5.0
    score = max(1.0, min(5.0, score))

    # Fetch existing rating to preserve feedback scores
    existing_rating = await db.execute(select(Rating).where(Rating.user_id == farmer_id, Rating.role == "FARMER"))
    existing_rating = existing_rating.scalar_one_or_none()

    # Update or create rating
    rating = existing_rating
    if not rating:
        rating = Rating(user_id=farmer_id, role="FARMER")
        db.add(rating)

    rating.overall_score = score
    rating.component_scores = {
        "agent_accuracy": agent_accuracy,
        "delivery_ratio": delivery_ratio,
        "efficiency_ratio": efficiency_ratio,
    }
    # Preserve any existing feedback scores
    if existing_rating and existing_rating.component_scores:
        for key in ("buyer_feedback", "agent_feedback"):
            if key in existing_rating.component_scores:
                rating.component_scores[key] = existing_rating.component_scores[key]

    rating.total_transactions = total_harvests
    rating.last_updated = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(rating)
    return rating


async def recalc_buyer_rating(db: AsyncSession, buyer_id: uuid.UUID) -> Rating:
    """Buyer rating based on:
       - Payment reliability (40%): ratio of orders paid vs total orders that reached DELIVERED or CANCELLED? We'll use successful completions.
       - Cancellation rate (40%): inverse of cancellation frequency.
       - Dispute frequency (20%): currently no disputes; placeholder 1.0.
    """
    orders = (await db.execute(select(Order).where(Order.buyer_id == buyer_id))).scalars().all()
    total_orders = len(orders)
    if total_orders == 0:
        # default neutral
        rating = await db.execute(select(Rating).where(Rating.user_id == buyer_id, Rating.role == "BUYER"))
        rating = rating.scalar_one_or_none()
        if not rating:
            rating = Rating(user_id=buyer_id, role="BUYER")
            db.add(rating)
            await db.commit()
        return rating

    # Payment reliability: orders that were fulfilled (RESERVED status is before delivery; we need to check if the shipment was delivered). Simpler: if order.status == FULFILLED? But we haven't set that. We'll assume if shipment was delivered, order is successful.
    fulfilled = 0
    cancelled = 0
    for o in orders:
        if o.status == OrderStatus.CANCELLED:
            cancelled += 1
        elif o.shipment_id:
            shipment = (await db.execute(select(Shipment).where(Shipment.id == o.shipment_id))).scalar_one_or_none()
            if shipment and shipment.status == ShipmentStatus.DELIVERED:
                fulfilled += 1
    # For remaining orders (pending/reserved without delivery), we don't penalize
    payment_score = (fulfilled / max(1, fulfilled + cancelled)) if (fulfilled + cancelled) > 0 else 0.5

    # Cancellation frequency: 1 - (cancelled / total_orders)
    cancel_score = 1.0 - (cancelled / total_orders)

    # Dispute placeholder
    dispute_score = 1.0

    score = (0.4 * payment_score + 0.4 * cancel_score + 0.2 * dispute_score) * 5.0
    score = max(1.0, min(5.0, score))

    rating = await db.execute(select(Rating).where(Rating.user_id == buyer_id, Rating.role == "BUYER"))
    rating = rating.scalar_one_or_none()
    if not rating:
        rating = Rating(user_id=buyer_id, role="BUYER")
        db.add(rating)

    rating.overall_score = score
    rating.component_scores = {
        "payment_reliability": payment_score,
        "cancellation_rate": cancel_score,
        "dispute_frequency": dispute_score,
    }
    rating.total_transactions = total_orders
    rating.last_updated = datetime.now(timezone.utc)
    await db.commit()
    return rating


async def recalc_agent_rating(db: AsyncSession, agent_id: uuid.UUID) -> Rating:
    """Agent rating based on:
       - Verification accuracy (40%): how close claimed vs actual over time.
       - Response speed (20%): average time between shipment verification start and report submission.
       - Dispute frequency (40%): placeholder.
    """
    reports = (await db.execute(
        select(VerificationReport).where(VerificationReport.agent_id == agent_id)
    )).scalars().all()

    total = len(reports)
    if total == 0:
        rating = await db.execute(select(Rating).where(Rating.user_id == agent_id, Rating.role == "AGENT"))
        rating = rating.scalar_one_or_none()
        if not rating:
            rating = Rating(user_id=agent_id, role="AGENT")
            db.add(rating)
            await db.commit()
        return rating

    # Accuracy: similar to farmer, average of actual/claimed
    acc_sum = 0.0
    acc_count = 0
    for r in reports:
        if r.claimed_quantity_bags and r.actual_quantity_bags and r.claimed_quantity_bags > 0:
            acc_sum += min(r.actual_quantity_bags / r.claimed_quantity_bags, 1.0)
            acc_count += 1
    accuracy = (acc_sum / acc_count) if acc_count > 0 else 1.0

    # Response speed: average difference between server_timestamp and client_timestamp? Not stored. We'll use a placeholder of 1.0 for now.
    speed_score = 1.0

    dispute_score = 1.0

    score = (0.4 * accuracy + 0.2 * speed_score + 0.4 * dispute_score) * 5.0
    score = max(1.0, min(5.0, score))

    rating = await db.execute(select(Rating).where(Rating.user_id == agent_id, Rating.role == "AGENT"))
    rating = rating.scalar_one_or_none()
    if not rating:
        rating = Rating(user_id=agent_id, role="AGENT")
        db.add(rating)

    rating.overall_score = score
    rating.component_scores = {
        "verification_accuracy": accuracy,
        "response_speed": speed_score,
        "dispute_frequency": dispute_score,
    }
    rating.total_transactions = total
    rating.last_updated = datetime.now(timezone.utc)
    await db.commit()
    return rating


# Top-level recalculation triggered by events (e.g., after verification, after delivery)
async def update_ratings_for_shipment(db: AsyncSession, shipment: Shipment):
    """Recalc ratings for all farmers, buyers, agents involved in a shipment."""
    # Farmers via harvests
    harvests = (await db.execute(
        select(Harvest).where(Harvest.shipment_id == shipment.id)
    )).scalars().all()
    for h in harvests:
        await recalc_farmer_rating(db, h.farmer_id)

    # Buyers via orders
    orders = (await db.execute(
        select(Order).where(Order.shipment_id == shipment.id)
    )).scalars().all()
    for o in orders:
        await recalc_buyer_rating(db, o.buyer_id)

    # Agents via verifications
    verifs = (await db.execute(
        select(VerificationReport).where(VerificationReport.shipment_id == shipment.id)
    )).scalars().all()
    for v in verifs:
        await recalc_agent_rating(db, v.agent_id)


async def update_farmer_rating_from_feedback(db: AsyncSession, farmer_id: uuid.UUID):
    """Recalculate farmer rating after new feedback is submitted."""
    # Fetch all feedback for this farmer
    feedback_query = select(Feedback).where(Feedback.to_user_id == farmer_id)
    feedbacks = (await db.execute(feedback_query)).scalars().all()

    buyer_ratings = [f.rating for f in feedbacks if f.feedback_type == FeedbackType.BUYER_TO_FARMER]
    agent_ratings = [f.rating for f in feedbacks if f.feedback_type == FeedbackType.AGENT_TO_FARMER]

    # Compute average scores (or use weighted, recency, etc.)
    avg_buyer = sum(buyer_ratings) / len(buyer_ratings) if buyer_ratings else 3.0  # neutral default
    avg_agent = sum(agent_ratings) / len(agent_ratings) if agent_ratings else 3.0

    # Recalc the automatic score first, then blend with feedback.
    rating = await recalc_farmer_rating(db, farmer_id)  # updates automatic components

    # Now blend feedback: 60% automatic, 20% buyer feedback, 20% agent feedback
    automatic_score = rating.overall_score  # 1-5
    blended_score = (0.6 * automatic_score) + (0.2 * avg_buyer) + (0.2 * avg_agent)
    blended_score = max(1.0, min(5.0, blended_score))

    # Update the rating record with the blended score and store feedback components
    rating.overall_score = blended_score
    if rating.component_scores:
        rating.component_scores["buyer_feedback"] = avg_buyer
        rating.component_scores["agent_feedback"] = avg_agent
    else:
        rating.component_scores = {
            "buyer_feedback": avg_buyer,
            "agent_feedback": avg_agent,
        }
    rating.last_updated = datetime.now(timezone.utc)
    await db.commit()
    return rating