"""
Unit tests for AWS Capacity Reservation Manager - Simplified Version
"""

import unittest
from unittest import mock
from datetime import datetime, timedelta
from botocore.exceptions import ClientError

from cloud.aws.managers.capacity_reservation_manager import CapacityReservationManager


class TestCapacityReservationManager(unittest.TestCase):
    """Test suite for Capacity Reservation Manager"""

    def setUp(self):
        """Set up test environment"""
        # Mock environment variables
        self.env_patcher = mock.patch.dict(
            'os.environ',
            {
                'AWS_DEFAULT_REGION': 'us-east-2',
                'RUN_ID': 'test-run-123',
                'SCENARIO_NAME': 'test-scenario',
                'SCENARIO_TYPE': 'capacity-test',
                'DELETION_DUE_TIME': (datetime.now() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
            }
        )
        self.env_patcher.start()

        # Mock boto3 EC2 client
        self.boto3_patcher = mock.patch('cloud.aws.managers.capacity_reservation_manager.boto3')
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
        manager = CapacityReservationManager(region='us-west-2')
        self.assertEqual(manager.region, 'us-west-2')

    def test_init_with_env_region(self):
        """Test initialization using environment variable region"""
        self.assertEqual(self.manager.region, 'us-east-2')

    def test_init_without_region_raises_error(self):
        """Test initialization without region raises ValueError"""
        with mock.patch.dict('os.environ', {}, clear=True):
            with mock.patch('cloud.aws.managers.capacity_reservation_manager.get_env_vars') as mock_get_env:
                mock_get_env.return_value = None
                with self.assertRaises(ValueError) as context:
                    CapacityReservationManager()
                self.assertIn("AWS region is required", str(context.exception))

    def test_describe_capacity_block_offerings_success(self):
        """Test successful capacity block offerings description"""
        # Mock API response
        mock_response = {
            'CapacityBlockOfferings': [
                {
                    'CapacityBlockOfferingId': 'cb-123456789',
                    'InstanceType': 'p5.48xlarge',
                    'InstanceCount': 1,
                    'UpfrontFee': '755.00',
                    'CurrencyCode': 'USD',
                    'CapacityDurationHours': 24,
                    'AvailabilityZone': 'us-east-2a',
                    'StartDate': datetime(2025, 8, 15, 11, 30),
                    'EndDate': datetime(2025, 8, 16, 11, 30)
                }
            ]
        }
        self.mock_ec2.describe_capacity_block_offerings.return_value = mock_response

        # Call method
        offerings = self.manager.describe_capacity_block_offerings(
            instance_type='p5.48xlarge',
            instance_count=1,
            capacity_duration_hours=24
        )

        # Verify results
        self.assertEqual(len(offerings), 1)
        self.assertEqual(offerings[0]['CapacityBlockOfferingId'], 'cb-123456789')
        self.assertEqual(offerings[0]['InstanceType'], 'p5.48xlarge')
        self.assertEqual(offerings[0]['UpfrontFee'], '755.00')

        # Verify API call parameters
        self.mock_ec2.describe_capacity_block_offerings.assert_called_once()
        call_args = self.mock_ec2.describe_capacity_block_offerings.call_args[1]
        self.assertEqual(call_args['InstanceType'], 'p5.48xlarge')
        self.assertEqual(call_args['InstanceCount'], 1)
        self.assertEqual(call_args['CapacityDurationHours'], 24)

    def test_describe_capacity_block_offerings_with_start_date(self):
        """Test capacity block offerings description with start date"""
        start_date = datetime(2025, 8, 15, 0, 0)
        
        self.mock_ec2.describe_capacity_block_offerings.return_value = {
            'CapacityBlockOfferings': []
        }

        # Call method with start date
        self.manager.describe_capacity_block_offerings(
            instance_type='p5.48xlarge',
            instance_count=1,
            start_date_range=start_date,
            capacity_duration_hours=24
        )

        # Verify API call includes start date
        call_args = self.mock_ec2.describe_capacity_block_offerings.call_args[1]
        self.assertIn('StartDateRange', call_args)
        self.assertEqual(call_args['StartDateRange'], start_date)

    def test_describe_capacity_block_offerings_with_dry_run(self):
        """Test capacity block offerings description with dry run"""
        self.mock_ec2.describe_capacity_block_offerings.return_value = {
            'CapacityBlockOfferings': []
        }

        # Call method with dry run
        self.manager.describe_capacity_block_offerings(
            instance_type='p5.48xlarge',
            instance_count=1,
            dry_run=True
        )

        # Verify API call includes dry run
        call_args = self.mock_ec2.describe_capacity_block_offerings.call_args[1]
        self.assertTrue(call_args['DryRun'])

    def test_describe_capacity_block_offerings_invalid_params(self):
        """Test capacity block offerings description with invalid parameters"""
        # Test missing instance_type
        with self.assertRaises(ValueError) as context:
            self.manager.describe_capacity_block_offerings(
                instance_type="",
                instance_count=1
            )
        self.assertIn("instance_type is required", str(context.exception))

        # Test invalid instance_count
        with self.assertRaises(ValueError) as context:
            self.manager.describe_capacity_block_offerings(
                instance_type="p5.48xlarge",
                instance_count=0
            )
        self.assertIn("instance_count must be greater than 0", str(context.exception))

    def test_describe_capacity_block_offerings_client_error(self):
        """Test capacity block offerings description with AWS client error"""
        # Mock ClientError
        error_response = {
            'Error': {
                'Code': 'InvalidParameterValue',
                'Message': 'Invalid instance type'
            }
        }
        self.mock_ec2.describe_capacity_block_offerings.side_effect = ClientError(
            error_response, 'DescribeCapacityBlockOfferings'
        )

        # Expect ClientError to be raised
        with self.assertRaises(ClientError):
            self.manager.describe_capacity_block_offerings(
                instance_type='invalid-type',
                instance_count=1
            )

    def test_purchase_capacity_block_success(self):
        """Test successful capacity block purchase"""
        # Mock API response
        mock_response = {
            'CapacityReservation': {
                'CapacityReservationId': 'cr-123456789',
                'InstanceType': 'p5.48xlarge',
                'TotalInstanceCount': 1,
                'State': 'payment-pending',
                'AvailabilityZone': 'us-east-2a'
            }
        }
        self.mock_ec2.purchase_capacity_block.return_value = mock_response

        # Call method
        response = self.manager.purchase_capacity_block(
            capacity_block_offering_id='cb-123456789',
            instance_platform='Linux/UNIX'
        )

        # Verify results
        self.assertEqual(response['CapacityReservation']['CapacityReservationId'], 'cr-123456789')
        self.assertEqual(response['CapacityReservation']['State'], 'payment-pending')

        # Verify API call
        self.mock_ec2.purchase_capacity_block.assert_called_once()
        call_args = self.mock_ec2.purchase_capacity_block.call_args[1]
        self.assertEqual(call_args['CapacityBlockOfferingId'], 'cb-123456789')
        self.assertEqual(call_args['InstancePlatform'], 'Linux/UNIX')

    def test_purchase_capacity_block_invalid_params(self):
        """Test capacity block purchase with invalid parameters"""
        with self.assertRaises(ValueError) as context:
            self.manager.purchase_capacity_block(
                capacity_block_offering_id=""
            )
        self.assertIn("capacity_block_offering_id is required", str(context.exception))

    def test_purchase_capacity_block_client_error(self):
        """Test capacity block purchase with AWS client error"""
        error_response = {
            'Error': {
                'Code': 'InsufficientFunds',
                'Message': 'Insufficient funds for purchase'
            }
        }
        self.mock_ec2.purchase_capacity_block.side_effect = ClientError(
            error_response, 'PurchaseCapacityBlock'
        )

        with self.assertRaises(ClientError):
            self.manager.purchase_capacity_block(
                capacity_block_offering_id='cb-123456789'
            )

    def test_describe_capacity_reservations_success(self):
        """Test describing capacity reservations"""
        mock_response = {
            'CapacityReservations': [
                {
                    'CapacityReservationId': 'cr-123456789',
                    'InstanceType': 'p5.48xlarge',
                    'AvailabilityZone': 'us-east-2a',
                    'TotalInstanceCount': 1,
                    'AvailableInstanceCount': 1,
                    'State': 'active'
                }
            ]
        }
        self.mock_ec2.describe_capacity_reservations.return_value = mock_response

        # Call method
        reservations = self.manager.describe_capacity_reservations(
            instance_type='p5.48xlarge',
            state='active'
        )

        # Verify results
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0]['CapacityReservationId'], 'cr-123456789')
        self.assertEqual(reservations[0]['State'], 'active')

        # Verify API call with filters
        call_args = self.mock_ec2.describe_capacity_reservations.call_args[1]
        self.assertIn('Filters', call_args)
        filters = call_args['Filters']
        
        filter_names = [f['Name'] for f in filters]
        self.assertIn('instance-type', filter_names)
        self.assertIn('state', filter_names)

    def test_describe_capacity_reservations_with_ids(self):
        """Test describing specific capacity reservations by ID"""
        mock_response = {
            'CapacityReservations': [
                {
                    'CapacityReservationId': 'cr-123456789',
                    'InstanceType': 'p5.48xlarge',
                    'State': 'active'
                }
            ]
        }
        self.mock_ec2.describe_capacity_reservations.return_value = mock_response

        # Call method with specific IDs
        reservations = self.manager.describe_capacity_reservations(
            capacity_reservation_ids=['cr-123456789']
        )

        # Verify results
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0]['CapacityReservationId'], 'cr-123456789')

        # Verify API call includes reservation IDs
        call_args = self.mock_ec2.describe_capacity_reservations.call_args[1]
        self.assertIn('CapacityReservationIds', call_args)
        self.assertEqual(call_args['CapacityReservationIds'], ['cr-123456789'])

    def test_get_capacity_reservation_summary_success(self):
        """Test getting capacity reservation summary"""
        mock_reservation = {
            'CapacityReservationId': 'cr-123456789',
            'InstanceType': 'p5.48xlarge',
            'AvailabilityZone': 'us-east-2a',
            'State': 'active',
            'TotalInstanceCount': 1,
            'AvailableInstanceCount': 1,
            'StartDate': datetime(2025, 8, 15, 11, 30),
            'EndDate': datetime(2025, 8, 16, 11, 30),
            'InstancePlatform': 'Linux/UNIX',
            'Tenancy': 'default',
            'CapacityReservationType': 'capacity-block'
        }

        with mock.patch.object(self.manager, 'describe_capacity_reservations') as mock_describe:
            mock_describe.return_value = [mock_reservation]

            # Get summary
            summary = self.manager.get_capacity_reservation_summary('cr-123456789')

            # Verify summary content
            self.assertEqual(summary['capacity_reservation_id'], 'cr-123456789')
            self.assertEqual(summary['instance_type'], 'p5.48xlarge')
            self.assertEqual(summary['state'], 'active')
            self.assertEqual(summary['total_instance_count'], 1)
            self.assertEqual(summary['available_instance_count'], 1)
            self.assertEqual(summary['availability_zone'], 'us-east-2a')

    def test_get_capacity_reservation_summary_not_found(self):
        """Test getting capacity reservation summary when reservation doesn't exist"""
        with mock.patch.object(self.manager, 'describe_capacity_reservations') as mock_describe:
            mock_describe.return_value = []

            # Expect ValueError when reservation not found
            with self.assertRaises(ValueError) as context:
                self.manager.get_capacity_reservation_summary('cr-nonexistent')
            
            self.assertIn("not found", str(context.exception))


if __name__ == '__main__':
    unittest.main()
