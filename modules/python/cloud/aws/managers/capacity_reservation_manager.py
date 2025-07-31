"""
AWS Capacity Reservation Manager Module

This module provides functionality to manage AWS EC2 Capacity Blocks including:
- Describing capacity block offerings
- Purchasing capacity blocks
- Managing capacity reservations

The module follows the telescope project patterns and integrates with boto3 for AWS operations.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from utils.logger_config import get_logger, setup_logging
from utils.common import get_env_vars

# Configure logging
setup_logging()
logger = get_logger(__name__)

# Suppress noisy AWS SDK logs
get_logger("boto3").setLevel(logging.WARNING)
get_logger("botocore").setLevel(logging.WARNING)


class CapacityReservationManager:
    """
    Manager for AWS EC2 Capacity Block operations.
    
    This class provides methods to describe capacity block offerings,
    purchase capacity blocks, and manage capacity reservations.
    """

    def __init__(self, region: Optional[str] = None):
        """
        Initialize the Capacity Reservation Manager.

        Args:
            region: AWS region to operate in. If not provided, uses AWS_DEFAULT_REGION env var.
        """
        self.region = region or get_env_vars("AWS_DEFAULT_REGION")
        if not self.region:
            raise ValueError("AWS region is required. Set AWS_DEFAULT_REGION environment variable or provide region parameter.")
        
        try:
            self.ec2 = boto3.client("ec2", region_name=self.region)
            logger.info("Successfully initialized Capacity Reservation Manager for region: %s", self.region)
        except Exception as e:
            logger.error("Failed to initialize EC2 client: %s", e)
            raise

    def describe_capacity_block_offerings(
        self,
        instance_type: str,
        instance_count: int,
        dry_run: bool = False,
        start_date_range: Optional[datetime] = None,
        capacity_duration_hours: Optional[int] = 24,
        **kwargs
    ) -> List[Dict]:
        """
        Describe available capacity block offerings.

        Args:
            instance_type: EC2 instance type (e.g., 'p3.2xlarge')
            instance_count: Number of instances needed
            dry_run: Check if you have required permissions without making the request
            start_date_range: Optional datetime for earliest start date
            capacity_duration_hours: Duration in hours for the capacity block
            **kwargs: Additional parameters for the API call

        Returns:
            List of capacity block offering dictionaries

        Raises:
            ClientError: If AWS API call fails
            ValueError: If required parameters are missing or invalid
        """
        if not instance_type:
            raise ValueError("instance_type is required")
        
        if instance_count <= 0:
            raise ValueError("instance_count must be greater than 0")

        try:
            logger.info(
                "Describing capacity block offerings for %s instances of type %s for %d hours",
                instance_count,
                instance_type,
                capacity_duration_hours
            )

            # Build the API request parameters using AWS API format
            params = {
                "InstanceType": instance_type,
                "InstanceCount": instance_count,
            }

            # Add optional parameters
            if dry_run:
                params["DryRun"] = dry_run
            
            if start_date_range:
                params["StartDateRange"] = start_date_range
            
            
            if capacity_duration_hours:
                params["CapacityDurationHours"] = 24 if capacity_duration_hours < 24 else capacity_duration_hours
        
            # Add any additional parameters
            params.update(kwargs)
            logger.info("API parameters: %s", params)

            # Make the API call
            response = self.ec2.describe_capacity_block_offerings(**params)
            
            offerings = response.get("CapacityBlockOfferings", [])
            
            logger.info(
                "Found %d capacity block offerings for %s %s instances",
                len(offerings),
                instance_count,
                instance_type
            )

            return offerings

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]
            logger.error(
                "Failed to describe capacity block offerings: %s - %s",
                error_code,
                error_message
            )
            raise
        except Exception as e:
            logger.error("Unexpected error describing capacity block offerings: %s", e)
            raise

    def purchase_capacity_block(
        self,
        capacity_block_offering_id: str,
        instance_platform: str = "Linux/UNIX",
        tags: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Purchase a capacity block from an offering.

        Args:
            capacity_block_offering_id: ID of the capacity block offering to purchase
            instance_platform: Platform for the instances (default: 'Linux/UNIX')
            tags: Optional list of tags to apply to the capacity reservation

        Returns:
            Dictionary containing purchase details including CapacityReservationId

        Raises:
            ClientError: If AWS API call fails
            ValueError: If required parameters are missing or invalid
        """
        if not capacity_block_offering_id:
            raise ValueError("capacity_block_offering_id is required")

        try:
            logger.info("Purchasing capacity block with offering ID: %s", capacity_block_offering_id)

            # Build the API request parameters
            params = {
                "CapacityBlockOfferingId": capacity_block_offering_id,
                "InstancePlatform": instance_platform
            }

            # Make the API call
            response = self.ec2.purchase_capacity_block(**params)

            capacity_reservation = response.get("CapacityReservation", {})
            capacity_reservation_id = capacity_reservation.get("CapacityReservationId")

            logger.info(
                "Successfully purchased capacity block. Reservation ID: %s",
                capacity_reservation_id
            )

            # Log additional details
            logger.info(
                "Capacity reservation details: Instance type=%s, Count=%d, State=%s",
                capacity_reservation.get("InstanceType"),
                capacity_reservation.get("TotalInstanceCount", 0),
                capacity_reservation.get("State")
            )

            return response

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]
            logger.error(
                "Failed to purchase capacity block %s: %s - %s",
                capacity_block_offering_id,
                error_code,
                error_message
            )
            raise
        except Exception as e:
            logger.error("Unexpected error purchasing capacity block: %s", e)
            raise

    def describe_capacity_reservations(
        self,
        capacity_reservation_ids: Optional[List[str]] = None,
        instance_type: Optional[str] = None,
        availability_zone: Optional[str] = None,
        state: Optional[str] = None,
        **kwargs
    ) -> List[Dict]:
        """
        Describe existing capacity reservations.

        Args:
            capacity_reservation_ids: Optional list of specific reservation IDs to describe
            instance_type: Optional filter by instance type
            availability_zone: Optional filter by availability zone
            state: Optional filter by state ('active', 'expired', 'cancelled', etc.)
            **kwargs: Additional parameters for the API call

        Returns:
            List of capacity reservation dictionaries

        Raises:
            ClientError: If AWS API call fails
        """
        try:
            logger.info("Describing capacity reservations")

            # Build the API request parameters
            params = {}

            if capacity_reservation_ids:
                params["CapacityReservationIds"] = capacity_reservation_ids

            # Build filters
            filters = []
            if instance_type:
                filters.append({"Name": "instance-type", "Values": [instance_type]})
            if availability_zone:
                filters.append({"Name": "availability-zone", "Values": [availability_zone]})
            if state:
                filters.append({"Name": "state", "Values": [state]})

            if filters:
                params["Filters"] = filters

            # Add any additional parameters
            params.update(kwargs)

            # Make the API call
            response = self.ec2.describe_capacity_reservations(**params)

            reservations = response.get("CapacityReservations", [])

            logger.info("Found %d capacity reservations", len(reservations))

            # Log reservation details for debugging
            for i, reservation in enumerate(reservations):
                logger.debug(
                    "Reservation %d: ID=%s, Type=%s, Count=%d/%d, State=%s, AZ=%s",
                    i + 1,
                    reservation.get("CapacityReservationId"),
                    reservation.get("InstanceType"),
                    reservation.get("AvailableInstanceCount", 0),
                    reservation.get("TotalInstanceCount", 0),
                    reservation.get("State"),
                    reservation.get("AvailabilityZone")
                )

            return reservations

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]
            logger.error(
                "Failed to describe capacity reservations: %s - %s",
                error_code,
                error_message
            )
            raise
        except Exception as e:
            logger.error("Unexpected error describing capacity reservations: %s", e)
            raise

    def get_capacity_reservation_summary(self, capacity_reservation_id: str) -> Dict:
        """
        Get a summary of capacity reservation details.

        Args:
            capacity_reservation_id: ID of the capacity reservation

        Returns:
            Dictionary with summarized reservation details

        Raises:
            ClientError: If AWS API call fails
            ValueError: If reservation not found
        """
        reservations = self.describe_capacity_reservations(
            capacity_reservation_ids=[capacity_reservation_id]
        )

        if not reservations:
            raise ValueError(f"Capacity reservation {capacity_reservation_id} not found")

        reservation = reservations[0]

        return {
            "capacity_reservation_id": capacity_reservation_id,
            "instance_type": reservation.get("InstanceType"),
            "availability_zone": reservation.get("AvailabilityZone"),
            "state": reservation.get("State"),
            "total_instance_count": reservation.get("TotalInstanceCount", 0),
            "available_instance_count": reservation.get("AvailableInstanceCount", 0),
            "start_date": reservation.get("StartDate"),
            "end_date": reservation.get("EndDate"),
            "instance_platform": reservation.get("InstancePlatform"),
            "tenancy": reservation.get("Tenancy"),
            "capacity_type": reservation.get("CapacityReservationType")
        }


if __name__ == "__main__":
    import argparse
    from datetime import datetime
    
    # Set up command line argument parsing
    parser = argparse.ArgumentParser(description='AWS Capacity Reservation Manager - Find and Purchase Capacity Blocks')
    parser.add_argument('--region', '-r', default='us-east-2', help='AWS region (default: us-east-2)')
    parser.add_argument('--instance-type', '-t', required=True, help='EC2 instance type (e.g., p5.48xlarge)')
    parser.add_argument('--instance-count', '-c', type=int, required=True, help='Number of instances needed')
    parser.add_argument('--start-date', '-s', required=True, help='Start date in YYYY-MM-DD format')
    parser.add_argument('--duration-hours', '-d', type=int, required=True, help='Duration in hours')
    parser.add_argument('--dry-run', action='store_true', help='Only search for offerings, do not purchase')

    
    args = parser.parse_args()
        
    try:
        # Parse the start date
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
        
        # Initialize manager
        manager = CapacityReservationManager(region=args.region)
        
        # Search for capacity block offerings
        logger.info("Searching for capacity block offerings...")
        offerings = manager.describe_capacity_block_offerings(
            instance_type=args.instance_type,
            instance_count=args.instance_count,
            start_date_range=start_date,
            capacity_duration_hours=args.duration_hours,
        )
        
        if not offerings:
            logger.info("No capacity block offerings found for the specified criteria.")
            exit(1)
        
        # Sort by price (ascending) to get the cheapest option
        offerings.sort(key=lambda x: float(x.get("UpfrontFee")))
        
        # Display the best (cheapest) offering
        best_offering = offerings[0]
        logger.info("Best (cheapest) offering found:")
        logger.info("ID: %s", best_offering.get('CapacityBlockOfferingId'))
        logger.info("Instance Type: %s", best_offering.get('InstanceType'))
        logger.info("Instance Count: %s", best_offering.get('InstanceCount'))
        logger.info("Price: %s %s", best_offering.get('CurrencyCode', 'USD'), best_offering.get('UpfrontFee'))
        logger.info("Duration: %s hours", best_offering.get('CapacityBlockDurationHours'))
        logger.info("Availability Zone: %s", best_offering.get('AvailabilityZone'))
        logger.info("Start Date: %s", best_offering.get('StartDate'))
        logger.info("End Date: %s", best_offering.get('EndDate'))
        
        # Purchase the capacity block if not dry run
        if args.dry_run:
            logger.info("Dry run mode - not purchasing capacity block")
        else:
            logger.info("Purchasing capacity block...")                       
            # Purchase the capacity block
            response = manager.purchase_capacity_block(
                capacity_block_offering_id=best_offering['CapacityBlockOfferingId'],
                instance_platform='Linux/UNIX'
            )
            
            # Extract reservation details
            capacity_reservation = response.get("CapacityReservation", {})
            reservation_id = capacity_reservation.get("CapacityReservationId")
            
            logger.info("Capacity block purchased successfully!")
            logger.info("Reservation ID: %s", reservation_id)
            logger.info("State: %s", capacity_reservation.get('State'))
            logger.info("Instance Type: %s", capacity_reservation.get('InstanceType'))
            logger.info("Total Instances: %s", capacity_reservation.get('TotalInstanceCount'))
            logger.info("Availability Zone: %s", capacity_reservation.get('AvailabilityZone'))
            
            summary = manager.get_capacity_reservation_summary(reservation_id)
            logger.info("Final Reservation Summary:")
            for key, value in summary.items():
                logger.info("   %s: %s", key.replace('_', ' ').title(), value)
                
    except ValueError as e:
        logger.error("Invalid input: %s", e)
        logger.error("Please check your date format (YYYY-MM-DD) and other parameters.")
        exit(1)
    except Exception as e:
        logger.error("Error: %s", e)
        exit(1)
    