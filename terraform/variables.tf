variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment tag"
  type        = string
  default     = "demo"
}

variable "prefix" {
  description = "Prefix for all resource names"
  type        = string
  default     = "techstream"
}

variable "your_ip_cidr" {
  description = "Your IP address in CIDR notation for SSH access (e.g. 1.2.3.4/32)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "alert_email" {
  description = "Email to receive SNS alert notifications (leave empty to skip)"
  type        = string
  default     = ""
}

variable "ec2_instance_type" {
  description = "EC2 instance type for the TechStream application"
  type        = string
  default     = "t3.small"
}

variable "asg_min_size" {
  description = "ASG minimum capacity"
  type        = number
  default     = 1
}

variable "asg_max_size" {
  description = "ASG maximum capacity"
  type        = number
  default     = 4
}

variable "asg_desired_capacity" {
  description = "ASG desired capacity"
  type        = number
  default     = 1
}

variable "enable_devops_guru" {
  description = "Enable Amazon DevOps Guru on the stack"
  type        = bool
  default     = false
}
