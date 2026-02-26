"""Ride state model — injected into the LLM on every turn."""

from dataclasses import dataclass

from vehicle_api.state import CabinState


@dataclass
class RideContext:
    route_name: str
    current_stop: str
    next_stop: str
    eta_seconds: int
    ride_duration_seconds: int
    elapsed_seconds: int
    hour_of_day: int
    passenger_count: int | None
    cabin: CabinState

    def to_json_block(self) -> str:
        """Serialize for injection into the system prompt."""
        return (
            f"route_name={self.route_name!r}, current_stop={self.current_stop!r}, "
            f"next_stop={self.next_stop!r}, eta_seconds={self.eta_seconds}, "
            f"ride_duration_seconds={self.ride_duration_seconds}, elapsed_seconds={self.elapsed_seconds}, "
            f"hour_of_day={self.hour_of_day}, passenger_count={self.passenger_count}, "
            f"cabin={self.cabin.to_dict()}"
        )


def make_mock_context(
    route_name: str = "Downtown Loop",
    current_stop: str = "Main St",
    next_stop: str = "Civic Center",
    eta_seconds: int = 180,
    ride_duration_seconds: int = 900,
    elapsed_seconds: int = 120,
    hour_of_day: int = 14,
    passenger_count: int | None = 2,
    cabin: CabinState | None = None,
) -> RideContext:
    """Build a RideContext for prototyping (CLI flags or mock config)."""
    return RideContext(
        route_name=route_name,
        current_stop=current_stop,
        next_stop=next_stop,
        eta_seconds=eta_seconds,
        ride_duration_seconds=ride_duration_seconds,
        elapsed_seconds=elapsed_seconds,
        hour_of_day=hour_of_day,
        passenger_count=passenger_count,
        cabin=cabin or CabinState(),
    )
