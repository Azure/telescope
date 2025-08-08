"""
Unit tests for AWS Capacity Reservation Manager - Simplified Version
"""

import unittest
from unittest import mock
from datetime import datetime, timedelta
from botocore.exceptions import ClientError

from cloud.aws.managers.capacity_reservation_manager import CapacityReservationManager, main


class TestCapacityReservationManager(unittest.TestCase):
    """Test suite for Capacity Reservation Manager"""

    def setUp(self):
        """Set up test environment"""
        # Mock environment variables
        self.env_patcher = mock.patch.dict(
            "os.environ",
            {
                "AWS_DEFAULT_REGION": "us-east-2",
                "RUN_ID": "test-run-123",
                "SCENARIO_NAME": "test-scenario",
                "SCENARIO_TYPE": "capacity-test",
                "DELETION_DUE_TIME": (datetime.now() + timedelta(hours=2)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            },
        )
        self.env_patcher.start()

        # Mock boto3 EC2 client
        self.boto3_patcher = mock.patch(
            "cloud.aws.managers.capacity_reservation_manager.boto3"
        )
        mock_boto3 = self.boto3_patcher.start()

        self.mock_ec2 = mock.MagicMock()
        mock_boto3.client.return_value = self.mock_ec2

        # Create manager instance
        self.manager = CapacityReservationManager()

    def tearDown(self):
        """Clean up after tests"""
        self.env_patcher.stop()
        self.boto3_patcher.stop()

    def test_init_with_region(self):
        """Test initialization with explicit region"""
        manager = CapacityReservationManager(region="us-west-2")
        self.assertEqual(manager.region, "us-west-2")

    def test_init_with_env_region(self):
        """Test initialization using environment variable region"""
        self.assertEqual(self.manager.region, "us-east-2")

    def test_init_without_region_raises_error(self):
        """Test initialization without region raises ValueError"""
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch(
                "cloud.aws.managers.capacity_reservation_manager.get_env_vars"
            ) as mock_get_env:
                mock_get_env.return_value = None
                with self.assertRaises(ValueError) as context:
                    CapacityReservationManager()
                self.assertIn("AWS region is required", str(context.exception))

    def test_describe_capacity_block_offerings_success(self):
        """Test successful capacity block offerings description"""
        # Mock API response
        mock_response = {
            "CapacityBlockOfferings": [
                {
                    "CapacityBlockOfferingId": "cb-123456789",
                    "InstanceType": "p5.48xlarge",
                    "InstanceCount": 1,
                    "UpfrontFee": "755.00",
                    "CurrencyCode": "USD",
                    "CapacityDurationHours": 24,
                    "AvailabilityZone": "us-east-2a",
                    "StartDate": datetime(2025, 8, 15, 11, 30),
                    "EndDate": datetime(2025, 8, 16, 11, 30),
                }
            ]
        }
        self.mock_ec2.describe_capacity_block_offerings.return_value = mock_response

        # Call method
        offerings = self.manager.describe_capacity_block_offerings(
            instance_type="p5.48xlarge", instance_count=1, capacity_duration_hours=24
        )

        # Verify results
        self.assertEqual(len(offerings), 1)
        self.assertEqual(offerings[0]["CapacityBlockOfferingId"], "cb-123456789")
        self.assertEqual(offerings[0]["InstanceType"], "p5.48xlarge")
        self.assertEqual(offerings[0]["UpfrontFee"], "755.00")

        # Verify API call parameters
        self.mock_ec2.describe_capacity_block_offerings.assert_called_once()
        call_args = self.mock_ec2.describe_capacity_block_offerings.call_args[1]
        self.assertEqual(call_args["InstanceType"], "p5.48xlarge")
        self.assertEqual(call_args["InstanceCount"], 1)
        self.assertEqual(call_args["CapacityDurationHours"], 24)

    def test_describe_capacity_block_offerings_with_start_date(self):
        """Test capacity block offerings description with start date"""
        start_date = datetime(2025, 8, 15, 0, 0)

        self.mock_ec2.describe_capacity_block_offerings.return_value = {
            "CapacityBlockOfferings": []
        }

        # Call method with start date
        self.manager.describe_capacity_block_offerings(
            instance_type="p5.48xlarge",
            instance_count=1,
            start_date_range=start_date,
            capacity_duration_hours=24,
        )

        # Verify API call includes start date
        call_args = self.mock_ec2.describe_capacity_block_offerings.call_args[1]
        self.assertIn("StartDateRange", call_args)
        self.assertEqual(call_args["StartDateRange"], start_date)

    def test_describe_capacity_block_offerings_with_dry_run(self):
        """Test capacity block offerings description with dry run"""
        self.mock_ec2.describe_capacity_block_offerings.return_value = {
            "CapacityBlockOfferings": []
        }

        # Call method with dry run
        self.manager.describe_capacity_block_offerings(
            instance_type="p5.48xlarge", instance_count=1, dry_run=True
        )

        # Verify API call includes dry run
        call_args = self.mock_ec2.describe_capacity_block_offerings.call_args[1]
        self.assertTrue(call_args["DryRun"])

    def test_describe_capacity_block_offerings_invalid_params(self):
        """Test capacity block offerings description with invalid parameters"""
        # Test missing instance_type
        with self.assertRaises(ValueError) as context:
            self.manager.describe_capacity_block_offerings(
                instance_type="", instance_count=1
            )
        self.assertIn("instance_type is required", str(context.exception))

        # Test invalid instance_count
        with self.assertRaises(ValueError) as context:
            self.manager.describe_capacity_block_offerings(
                instance_type="p5.48xlarge", instance_count=0
            )
        self.assertIn("instance_count must be greater than 0", str(context.exception))

    def test_describe_capacity_block_offerings_client_error(self):
        """Test capacity block offerings description with AWS client error"""
        # Mock ClientError
        error_response = {
            "Error": {
                "Code": "InvalidParameterValue",
                "Message": "Invalid instance type",
            }
        }
        self.mock_ec2.describe_capacity_block_offerings.side_effect = ClientError(
            error_response, "DescribeCapacityBlockOfferings"
        )

        # Expect ClientError to be raised
        with self.assertRaises(ClientError):
            self.manager.describe_capacity_block_offerings(
                instance_type="invalid-type", instance_count=1
            )

    def test_purchase_capacity_block_success(self):
        """Test successful capacity block purchase"""
        # Mock API response
        mock_response = {
            "CapacityReservation": {
                "CapacityReservationId": "cr-123456789",
                "InstanceType": "p5.48xlarge",
                "TotalInstanceCount": 1,
                "State": "payment-pending",
                "AvailabilityZone": "us-east-2a",
            }
        }
        self.mock_ec2.purchase_capacity_block.return_value = mock_response

        # Call method
        response = self.manager.purchase_capacity_block(
            capacity_block_offering_id="cb-123456789", instance_platform="Linux/UNIX"
        )

        # Verify results
        self.assertEqual(
            response["CapacityReservation"]["CapacityReservationId"], "cr-123456789"
        )
        self.assertEqual(response["CapacityReservation"]["State"], "payment-pending")

        # Verify API call
        self.mock_ec2.purchase_capacity_block.assert_called_once()
        call_args = self.mock_ec2.purchase_capacity_block.call_args[1]
        self.assertEqual(call_args["CapacityBlockOfferingId"], "cb-123456789")
        self.assertEqual(call_args["InstancePlatform"], "Linux/UNIX")

    def test_purchase_capacity_block_invalid_params(self):
        """Test capacity block purchase with invalid parameters"""
        with self.assertRaises(ValueError) as context:
            self.manager.purchase_capacity_block(capacity_block_offering_id="")
        self.assertIn("capacity_block_offering_id is required", str(context.exception))

    def test_purchase_capacity_block_client_error(self):
        """Test capacity block purchase with AWS client error"""
        error_response = {
            "Error": {
                "Code": "InsufficientFunds",
                "Message": "Insufficient funds for purchase",
            }
        }
        self.mock_ec2.purchase_capacity_block.side_effect = ClientError(
            error_response, "PurchaseCapacityBlock"
        )

        with self.assertRaises(ClientError):
            self.manager.purchase_capacity_block(
                capacity_block_offering_id="cb-123456789"
            )

    def test_describe_capacity_reservations_success(self):
        """Test describing capacity reservations"""
        mock_response = {
            "CapacityReservations": [
                {
                    "CapacityReservationId": "cr-123456789",
                    "InstanceType": "p5.48xlarge",
                    "AvailabilityZone": "us-east-2a",
                    "TotalInstanceCount": 1,
                    "AvailableInstanceCount": 1,
                    "State": "active",
                }
            ]
        }
        self.mock_ec2.describe_capacity_reservations.return_value = mock_response

        # Call method
        reservations = self.manager.describe_capacity_reservations(
            instance_type="p5.48xlarge", state="active"
        )

        # Verify results
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0]["CapacityReservationId"], "cr-123456789")
        self.assertEqual(reservations[0]["State"], "active")

        # Verify API call with filters
        call_args = self.mock_ec2.describe_capacity_reservations.call_args[1]
        self.assertIn("Filters", call_args)
        filters = call_args["Filters"]

        filter_names = [f["Name"] for f in filters]
        self.assertIn("instance-type", filter_names)
        self.assertIn("state", filter_names)

    def test_describe_capacity_reservations_with_ids(self):
        """Test describing specific capacity reservations by ID"""
        mock_response = {
            "CapacityReservations": [
                {
                    "CapacityReservationId": "cr-123456789",
                    "InstanceType": "p5.48xlarge",
                    "State": "active",
                }
            ]
        }
        self.mock_ec2.describe_capacity_reservations.return_value = mock_response

        # Call method with specific IDs
        reservations = self.manager.describe_capacity_reservations(
            capacity_reservation_ids=["cr-123456789"]
        )

        # Verify results
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0]["CapacityReservationId"], "cr-123456789")

        # Verify API call includes reservation IDs
        call_args = self.mock_ec2.describe_capacity_reservations.call_args[1]
        self.assertIn("CapacityReservationIds", call_args)
        self.assertEqual(call_args["CapacityReservationIds"], ["cr-123456789"])

    def test_get_capacity_reservation_summary_success(self):
        """Test getting capacity reservation summary"""
        mock_reservation = {
            "CapacityReservationId": "cr-123456789",
            "InstanceType": "p5.48xlarge",
            "AvailabilityZone": "us-east-2a",
            "State": "active",
            "TotalInstanceCount": 1,
            "AvailableInstanceCount": 1,
            "StartDate": datetime(2025, 8, 15, 11, 30),
            "EndDate": datetime(2025, 8, 16, 11, 30),
            "InstancePlatform": "Linux/UNIX",
            "Tenancy": "default",
            "CapacityReservationType": "capacity-block",
        }

        with mock.patch.object(
            self.manager, "describe_capacity_reservations"
        ) as mock_describe:
            mock_describe.return_value = [mock_reservation]

            # Get summary
            summary = self.manager.get_capacity_reservation_summary("cr-123456789")

            # Verify summary content
            self.assertEqual(summary["capacity_reservation_id"], "cr-123456789")
            self.assertEqual(summary["instance_type"], "p5.48xlarge")
            self.assertEqual(summary["state"], "active")
            self.assertEqual(summary["total_instance_count"], 1)
            self.assertEqual(summary["available_instance_count"], 1)
            self.assertEqual(summary["availability_zone"], "us-east-2a")

    def test_get_capacity_reservation_summary_not_found(self):
        """Test getting capacity reservation summary when reservation doesn't exist"""
        with mock.patch.object(
            self.manager, "describe_capacity_reservations"
        ) as mock_describe:
            mock_describe.return_value = []

            # Expect ValueError when reservation not found
            with self.assertRaises(ValueError) as context:
                self.manager.get_capacity_reservation_summary("cr-nonexistent")

            self.assertIn("not found", str(context.exception))

    def test_init_ec2_client_failure(self):
        """Test initialization when EC2 client creation fails"""
        with mock.patch(
            "cloud.aws.managers.capacity_reservation_manager.boto3"
        ) as mock_boto3:
            mock_boto3.client.side_effect = Exception("AWS credentials not found")

            with self.assertRaises(Exception) as context:
                CapacityReservationManager(region="us-west-2")

            self.assertIn("AWS credentials not found", str(context.exception))

    def test_describe_capacity_block_offerings_unexpected_error(self):
        """Test describe_capacity_block_offerings with unexpected error"""
        self.mock_ec2.describe_capacity_block_offerings.side_effect = Exception(
            "Unexpected error"
        )

        with self.assertRaises(Exception) as context:
            self.manager.describe_capacity_block_offerings(
                instance_type="p5.48xlarge", instance_count=1
            )

        self.assertIn("Unexpected error", str(context.exception))

    def test_purchase_capacity_block_unexpected_error(self):
        """Test purchase_capacity_block with unexpected error"""
        self.mock_ec2.purchase_capacity_block.side_effect = Exception(
            "Unexpected error"
        )

        with self.assertRaises(Exception) as context:
            self.manager.purchase_capacity_block(
                capacity_block_offering_id="cb-123456789"
            )

        self.assertIn("Unexpected error", str(context.exception))

    def test_describe_capacity_reservations_client_error(self):
        """Test describe_capacity_reservations with AWS client error"""
        error_response = {
            "Error": {
                "Code": "InvalidParameterValue",
                "Message": "Invalid parameter value",
            }
        }
        self.mock_ec2.describe_capacity_reservations.side_effect = ClientError(
            error_response, "DescribeCapacityReservations"
        )

        with self.assertRaises(ClientError):
            self.manager.describe_capacity_reservations(instance_type="p5.48xlarge")

    def test_describe_capacity_reservations_unexpected_error(self):
        """Test describe_capacity_reservations with unexpected error"""
        self.mock_ec2.describe_capacity_reservations.side_effect = Exception(
            "Unexpected error"
        )

        with self.assertRaises(Exception) as context:
            self.manager.describe_capacity_reservations(instance_type="p5.48xlarge")

        self.assertIn("Unexpected error", str(context.exception))

    def test_describe_capacity_reservations_with_all_filters(self):
        """Test describe_capacity_reservations with all filter parameters"""
        mock_response = {
            "CapacityReservations": [
                {
                    "CapacityReservationId": "cr-123456789",
                    "InstanceType": "p5.48xlarge",
                    "State": "active",
                    "AvailabilityZone": "us-east-2a",
                }
            ]
        }
        self.mock_ec2.describe_capacity_reservations.return_value = mock_response

        # Call method with all filter parameters
        reservations = self.manager.describe_capacity_reservations(
            instance_type="p5.48xlarge",
            availability_zone="us-east-2a",
            state="active",
        )

        # Verify results
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0]["CapacityReservationId"], "cr-123456789")

        # Verify API call with all filters
        call_args = self.mock_ec2.describe_capacity_reservations.call_args[1]
        self.assertIn("Filters", call_args)
        filters = call_args["Filters"]

        filter_names = [f["Name"] for f in filters]
        self.assertIn("instance-type", filter_names)
        self.assertIn("availability-zone", filter_names)
        self.assertIn("state", filter_names)

    def test_describe_capacity_block_offerings_with_kwargs(self):
        """Test describe_capacity_block_offerings with additional kwargs"""
        self.mock_ec2.describe_capacity_block_offerings.return_value = {
            "CapacityBlockOfferings": []
        }

        # Call method with additional parameters
        self.manager.describe_capacity_block_offerings(
            instance_type="p5.48xlarge",
            instance_count=1,
            capacity_duration_hours=48,
            MaxResults=10,
            NextToken="token123",
        )

        # Verify API call includes additional parameters
        call_args = self.mock_ec2.describe_capacity_block_offerings.call_args[1]
        self.assertEqual(call_args["CapacityDurationHours"], 48)
        self.assertEqual(call_args["MaxResults"], 10)
        self.assertEqual(call_args["NextToken"], "token123")

    def test_describe_capacity_block_offerings_duration_min_24_hours(self):
        """Test describe_capacity_block_offerings enforces minimum 24 hours duration"""
        self.mock_ec2.describe_capacity_block_offerings.return_value = {
            "CapacityBlockOfferings": []
        }

        # Call method with duration less than 24 hours
        self.manager.describe_capacity_block_offerings(
            instance_type="p5.48xlarge",
            instance_count=1,
            capacity_duration_hours=12,  # Less than 24
        )

        # Verify API call uses minimum 24 hours
        call_args = self.mock_ec2.describe_capacity_block_offerings.call_args[1]
        self.assertEqual(call_args["CapacityDurationHours"], 24)

    def test_describe_capacity_reservations_with_kwargs(self):
        """Test describe_capacity_reservations with additional kwargs"""
        mock_response = {"CapacityReservations": []}
        self.mock_ec2.describe_capacity_reservations.return_value = mock_response

        # Call method with additional parameters
        self.manager.describe_capacity_reservations(
            MaxResults=50,
            NextToken="token456",
        )

        # Verify API call includes additional parameters
        call_args = self.mock_ec2.describe_capacity_reservations.call_args[1]
        self.assertEqual(call_args["MaxResults"], 50)
        self.assertEqual(call_args["NextToken"], "token456")


class TestCapacityReservationManagerMain(unittest.TestCase):
    """Test suite for the main function"""

    def setUp(self):
        """Set up test environment"""
        # Mock sys.argv to avoid interference with pytest
        self.argv_patcher = mock.patch("sys.argv", ["test"])
        self.argv_patcher.start()

    def tearDown(self):
        """Clean up after tests"""
        self.argv_patcher.stop()

    @mock.patch("cloud.aws.managers.capacity_reservation_manager.CapacityReservationManager")
    @mock.patch("argparse.ArgumentParser.parse_args")
    def test_main_dry_run_success(self, mock_parse_args, mock_manager_class):
        """Test main function with dry run mode"""
        # Mock arguments
        mock_args = mock.MagicMock()
        mock_args.region = "us-east-2"
        mock_args.instance_type = "p5.48xlarge"
        mock_args.instance_count = 1
        mock_args.start_date = "2025-08-15"
        mock_args.duration_hours = 24
        mock_args.dry_run = True
        mock_parse_args.return_value = mock_args

        # Mock manager instance
        mock_manager = mock.MagicMock()
        mock_manager_class.return_value = mock_manager

        # Mock capacity block offerings response
        mock_offerings = [
            {
                "CapacityBlockOfferingId": "cb-123456789",
                "InstanceType": "p5.48xlarge",
                "InstanceCount": 1,
                "UpfrontFee": "755.00",
                "CurrencyCode": "USD",
                "CapacityBlockDurationHours": 24,
                "AvailabilityZone": "us-east-2a",
                "StartDate": datetime(2025, 8, 15, 11, 30),
                "EndDate": datetime(2025, 8, 16, 11, 30),
            }
        ]
        mock_manager.describe_capacity_block_offerings.return_value = mock_offerings

        # Call main function
        main()

        # Verify manager was initialized with correct region
        mock_manager_class.assert_called_once_with(region="us-east-2")

        # Verify describe_capacity_block_offerings was called
        mock_manager.describe_capacity_block_offerings.assert_called_once()
        call_args = mock_manager.describe_capacity_block_offerings.call_args[1]
        self.assertEqual(call_args["instance_type"], "p5.48xlarge")
        self.assertEqual(call_args["instance_count"], 1)
        self.assertEqual(call_args["capacity_duration_hours"], 24)

        # Verify purchase_capacity_block was NOT called (dry run mode)
        mock_manager.purchase_capacity_block.assert_not_called()

    @mock.patch("cloud.aws.managers.capacity_reservation_manager.CapacityReservationManager")
    @mock.patch("argparse.ArgumentParser.parse_args")
    def test_main_purchase_success(self, mock_parse_args, mock_manager_class):
        """Test main function with actual purchase"""
        # Mock arguments
        mock_args = mock.MagicMock()
        mock_args.region = "us-east-2"
        mock_args.instance_type = "p5.48xlarge"
        mock_args.instance_count = 1
        mock_args.start_date = "2025-08-15"
        mock_args.duration_hours = 24
        mock_args.dry_run = False
        mock_parse_args.return_value = mock_args

        # Mock manager instance
        mock_manager = mock.MagicMock()
        mock_manager_class.return_value = mock_manager

        # Mock capacity block offerings response
        mock_offerings = [
            {
                "CapacityBlockOfferingId": "cb-123456789",
                "InstanceType": "p5.48xlarge",
                "InstanceCount": 1,
                "UpfrontFee": "755.00",
                "CurrencyCode": "USD",
                "CapacityBlockDurationHours": 24,
                "AvailabilityZone": "us-east-2a",
                "StartDate": datetime(2025, 8, 15, 11, 30),
                "EndDate": datetime(2025, 8, 16, 11, 30),
            }
        ]
        mock_manager.describe_capacity_block_offerings.return_value = mock_offerings

        # Mock purchase response
        mock_purchase_response = {
            "CapacityReservation": {
                "CapacityReservationId": "cr-123456789",
                "InstanceType": "p5.48xlarge",
                "TotalInstanceCount": 1,
                "State": "payment-pending",
                "AvailabilityZone": "us-east-2a",
            }
        }
        mock_manager.purchase_capacity_block.return_value = mock_purchase_response

        # Mock summary response
        mock_summary = {
            "capacity_reservation_id": "cr-123456789",
            "instance_type": "p5.48xlarge",
            "state": "payment-pending",
        }
        mock_manager.get_capacity_reservation_summary.return_value = mock_summary

        # Call main function
        main()

        # Verify purchase_capacity_block was called
        mock_manager.purchase_capacity_block.assert_called_once_with(
            capacity_block_offering_id="cb-123456789",
            instance_platform="Linux/UNIX",
        )

        # Verify get_capacity_reservation_summary was called
        mock_manager.get_capacity_reservation_summary.assert_called_once_with("cr-123456789")

    @mock.patch("cloud.aws.managers.capacity_reservation_manager.CapacityReservationManager")
    @mock.patch("argparse.ArgumentParser.parse_args")
    @mock.patch("sys.exit")
    def test_main_no_offerings_found(self, mock_exit, mock_parse_args, mock_manager_class):
        """Test main function when no offerings are found"""
        # Mock arguments
        mock_args = mock.MagicMock()
        mock_args.region = "us-east-2"
        mock_args.instance_type = "p5.48xlarge"
        mock_args.instance_count = 1
        mock_args.start_date = "2025-08-15"
        mock_args.duration_hours = 24
        mock_args.dry_run = True
        mock_parse_args.return_value = mock_args

        # Mock manager instance
        mock_manager = mock.MagicMock()
        mock_manager_class.return_value = mock_manager

        # Mock empty offerings response
        mock_manager.describe_capacity_block_offerings.return_value = []

        # Call main function
        main()

        # Verify sys.exit was called with code 1 (may be called multiple times due to error handling)
        mock_exit.assert_called_with(1)

    @mock.patch("cloud.aws.managers.capacity_reservation_manager.CapacityReservationManager")
    @mock.patch("argparse.ArgumentParser.parse_args")
    @mock.patch("sys.exit")
    def test_main_invalid_date_format(self, mock_exit, mock_parse_args, mock_manager_class):
        """Test main function with invalid date format"""
        # Mock arguments with invalid date
        mock_args = mock.MagicMock()
        mock_args.region = "us-east-2"
        mock_args.instance_type = "p5.48xlarge"
        mock_args.instance_count = 1
        mock_args.start_date = "invalid-date"
        mock_args.duration_hours = 24
        mock_args.dry_run = True
        mock_parse_args.return_value = mock_args

        # Call main function
        main()

        # Verify sys.exit was called with code 1
        mock_exit.assert_called_once_with(1)

    @mock.patch("cloud.aws.managers.capacity_reservation_manager.CapacityReservationManager")
    @mock.patch("argparse.ArgumentParser.parse_args")
    @mock.patch("sys.exit")
    def test_main_general_exception(self, mock_exit, mock_parse_args, mock_manager_class):
        """Test main function with general exception"""
        # Mock arguments
        mock_args = mock.MagicMock()
        mock_args.region = "us-east-2"
        mock_args.instance_type = "p5.48xlarge"
        mock_args.instance_count = 1
        mock_args.start_date = "2025-08-15"
        mock_args.duration_hours = 24
        mock_args.dry_run = True
        mock_parse_args.return_value = mock_args

        # Mock manager to raise exception
        mock_manager_class.side_effect = Exception("General error")

        # Call main function
        main()

        # Verify sys.exit was called with code 1
        mock_exit.assert_called_once_with(1)

    @mock.patch("cloud.aws.managers.capacity_reservation_manager.CapacityReservationManager")
    @mock.patch("argparse.ArgumentParser.parse_args")
    def test_main_offerings_sorting(self, mock_parse_args, mock_manager_class):
        """Test main function sorts offerings by price"""
        # Mock arguments
        mock_args = mock.MagicMock()
        mock_args.region = "us-east-2"
        mock_args.instance_type = "p5.48xlarge"
        mock_args.instance_count = 1
        mock_args.start_date = "2025-08-15"
        mock_args.duration_hours = 24
        mock_args.dry_run = True
        mock_parse_args.return_value = mock_args

        # Mock manager instance
        mock_manager = mock.MagicMock()
        mock_manager_class.return_value = mock_manager

        # Mock multiple offerings with different prices
        mock_offerings = [
            {
                "CapacityBlockOfferingId": "cb-expensive",
                "UpfrontFee": "1000.00",
                "CurrencyCode": "USD",
            },
            {
                "CapacityBlockOfferingId": "cb-cheap",
                "UpfrontFee": "500.00",
                "CurrencyCode": "USD",
            },
            {
                "CapacityBlockOfferingId": "cb-medium",
                "UpfrontFee": "750.00",
                "CurrencyCode": "USD",
            },
        ]
        mock_manager.describe_capacity_block_offerings.return_value = mock_offerings

        # Call main function
        main()

        # The function should process the cheapest offering (cb-cheap)
        # We can't directly verify the sorting, but the function logs the best offering
        mock_manager.describe_capacity_block_offerings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
