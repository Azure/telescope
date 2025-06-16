locals {
  # NRMS Security Rules Configuration
  nrms_rules = {
    # High Priority Allow Rules
    "NRMS-Rule-101" = {
      name                       = "NRMS-Rule-101"
      priority                   = 101
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "443"
      source_address_prefix      = "VirtualNetwork"
      destination_address_prefix = "*"
      description                = "Allow 443 from Virtual Network"
    }
    "NRMS-Rule-103" = {
      name                       = "NRMS-Rule-103"
      priority                   = 103
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "*"
      source_port_range          = "*"
      destination_port_range     = "*"
      source_address_prefix      = "CorpNetPublic"
      destination_address_prefix = "*"
      description                = "Allow all traffic from CorpNetPublic"
    }
    "NRMS-Rule-104" = {
      name                       = "NRMS-Rule-104"
      priority                   = 104
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "*"
      source_port_range          = "*"
      destination_port_range     = "*"
      source_address_prefix      = "CorpNetSaw"
      destination_address_prefix = "*"
      description                = "Allow all traffic from CorpNetSaw"
    }
    
    # Database and Service Blocking Rules
    "NRMS-Rule-105" = {
      name                         = "NRMS-Rule-105"
      priority                     = 105
      direction                    = "Inbound"
      access                       = "Deny"
      protocol                     = "*"
      source_port_range            = "*"
      destination_port_ranges      = ["1433", "1434", "3306", "4333", "5432", "6379", "7000", "7001", "7199", "9042", "9160", "9300", "16379", "26379", "27017"]
      source_address_prefix        = "Internet"
      destination_address_prefix   = "*"
      description                  = "Block database ports from Internet"
    }
    "NRMS-Rule-106" = {
      name                       = "NRMS-Rule-106"
      priority                   = 106
      direction                  = "Inbound"
      access                     = "Deny"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_ranges    = ["22", "3389"]
      source_address_prefix      = "Internet"
      destination_address_prefix = "*"
      description                = "Block SSH and RDP from Internet"
    }
    "NRMS-Rule-107" = {
      name                       = "NRMS-Rule-107"
      priority                   = 107
      direction                  = "Inbound"
      access                     = "Deny"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_ranges    = ["23", "135", "445", "5985", "5986"]
      source_address_prefix      = "Internet"
      destination_address_prefix = "*"
      description                = "Block management ports from Internet"
    }
    "NRMS-Rule-108" = {
      name                       = "NRMS-Rule-108"
      priority                   = 108
      direction                  = "Inbound"
      access                     = "Deny"
      protocol                   = "*"
      source_port_range          = "*"
      destination_port_ranges    = ["13", "17", "19", "53", "69", "111", "123", "512", "514", "593", "873", "1900", "5353", "11211"]
      source_address_prefix      = "Internet"
      destination_address_prefix = "*"
      description                = "Block network service ports from Internet"
    }
    "NRMS-Rule-109" = {
      name                       = "NRMS-Rule-109"
      priority                   = 109
      direction                  = "Inbound"
      access                     = "Deny"
      protocol                   = "*"
      source_port_range          = "*"
      destination_port_ranges    = ["119", "137", "138", "139", "161", "162", "389", "636", "2049", "2301", "2381", "3268", "5800", "5900"]
      source_address_prefix      = "Internet"
      destination_address_prefix = "*"
      description                = "Block directory and legacy service ports from Internet"
    }    
  }
}

# Create all NRMS security rules
resource "azurerm_network_security_rule" "nrms_security_rules" {
  for_each = local.nrms_rules

  name                         = each.value.name
  priority                     = each.value.priority
  direction                    = each.value.direction
  access                       = each.value.access
  protocol                     = each.value.protocol
  source_port_range            = each.value.source_port_range
  destination_port_range       = try(each.value.destination_port_range, null)
  destination_port_ranges      = try(each.value.destination_port_ranges, null)
  source_address_prefix        = each.value.source_address_prefix
  destination_address_prefix   = each.value.destination_address_prefix
  resource_group_name          = var.resource_group_name
  network_security_group_name  = var.network_security_group_name
  description                  = each.value.description
}
