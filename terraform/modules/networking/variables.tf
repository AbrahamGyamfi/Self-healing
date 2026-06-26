variable "prefix" { type = string }
variable "aws_region" { type = string }
variable "your_ip_cidr" {
  type        = string
  description = "Your public IP in CIDR notation for SSH access (e.g. 1.2.3.4/32). No default — must be supplied explicitly."
  validation {
    condition     = var.your_ip_cidr != "0.0.0.0/0"
    error_message = "Do not use 0.0.0.0/0 for SSH access. Provide your specific IP (e.g. 203.0.113.10/32)."
  }
}
variable "alert_email" {
  type    = string
  default = ""
}
