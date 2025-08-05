"""
AWS Managers Package

This package contains managers for various AWS services used in the telescope project.
"""

from .capacity_reservation_manager import CapacityReservationManager

__all__ = ['CapacityReservationManager']
