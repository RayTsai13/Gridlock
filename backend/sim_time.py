"""Simulation clock and playback state for the visual heatmap."""

from __future__ import annotations

from dataclasses import dataclass


MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY
DEFAULT_TIME_BIN_MINUTES = 30
DEFAULT_SIM_STEP_SECONDS = 1800


@dataclass(frozen=True)
class SimTime:
    day_of_week: int
    time_bin: int
    minute_of_week: int

    @property
    def minute_of_day(self) -> int:
        return self.minute_of_week % MINUTES_PER_DAY

    @property
    def is_weekend(self) -> bool:
        return self.day_of_week in {0, 6}

    def to_dict(self) -> dict[str, int]:
        return {
            "day_of_week": self.day_of_week,
            "time_bin": self.time_bin,
            "minute_of_week": self.minute_of_week,
        }


def sim_time_for_tick(
    tick: int,
    *,
    sim_step_seconds: int = DEFAULT_SIM_STEP_SECONDS,
    time_bin_minutes: int = DEFAULT_TIME_BIN_MINUTES,
) -> SimTime:
    minute_of_week = (tick * sim_step_seconds // 60) % MINUTES_PER_WEEK
    minute_of_day = minute_of_week % MINUTES_PER_DAY
    return SimTime(
        day_of_week=minute_of_week // MINUTES_PER_DAY,
        time_bin=(minute_of_day // time_bin_minutes) * time_bin_minutes,
        minute_of_week=minute_of_week,
    )


@dataclass
class PlaybackController:
    frame_interval_seconds: float
    sim_step_seconds: int = DEFAULT_SIM_STEP_SECONDS
    time_bin_minutes: int = DEFAULT_TIME_BIN_MINUTES
    current_tick: int = 0
    is_playing: bool = True

    @property
    def current_time(self) -> SimTime:
        return sim_time_for_tick(
            self.current_tick,
            sim_step_seconds=self.sim_step_seconds,
            time_bin_minutes=self.time_bin_minutes,
        )

    @property
    def sim_minutes_per_second(self) -> float:
        if self.frame_interval_seconds <= 0:
            return 0.0
        return (self.sim_step_seconds / 60.0) / self.frame_interval_seconds

    def advance(self) -> SimTime:
        if self.is_playing:
            self.current_tick += 1
        return self.current_time

    def set_playing(self, is_playing: bool) -> None:
        self.is_playing = bool(is_playing)

    def set_speed(self, sim_minutes_per_second: float) -> None:
        if sim_minutes_per_second <= 0:
            raise ValueError("sim_minutes_per_second must be positive")
        self.sim_step_seconds = max(
            60,
            int(round(sim_minutes_per_second * 60.0 * self.frame_interval_seconds)),
        )

    def seek(
        self,
        *,
        minute_of_week: int | None = None,
        day_of_week: int | None = None,
        time_bin: int | None = None,
    ) -> SimTime:
        if minute_of_week is None:
            if day_of_week is None or time_bin is None:
                raise ValueError("Provide minute_of_week or both day_of_week and time_bin")
            minute_of_week = (int(day_of_week) % 7) * MINUTES_PER_DAY + int(time_bin)
        seconds = (int(minute_of_week) % MINUTES_PER_WEEK) * 60
        self.current_tick = seconds // self.sim_step_seconds
        return self.current_time

    def to_dict(self) -> dict[str, object]:
        return {
            "is_playing": self.is_playing,
            "current_tick": self.current_tick,
            "sim_step_seconds": self.sim_step_seconds,
            "sim_minutes_per_second": self.sim_minutes_per_second,
            "frame_interval_seconds": self.frame_interval_seconds,
            "time_bin_minutes": self.time_bin_minutes,
            "sim_time": self.current_time.to_dict(),
        }
