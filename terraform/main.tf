terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "TechStream-SelfHealing"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# ---------------------------------------------------------------------------
# Modules — wired in dependency order
# ---------------------------------------------------------------------------

module "networking" {
  source       = "./modules/networking"
  prefix       = var.prefix
  aws_region   = var.aws_region
  your_ip_cidr = var.your_ip_cidr
  alert_email  = var.alert_email
}

module "iam" {
  source        = "./modules/iam"
  prefix        = var.prefix
  sns_topic_arn = module.networking.sns_topic_arn
  asg_arn       = module.compute.asg_arn
}

module "compute" {
  source               = "./modules/compute"
  prefix               = var.prefix
  vpc_id               = module.networking.vpc_id
  subnet_ids           = module.networking.subnet_ids
  sg_id                = module.networking.sg_id
  instance_profile_arn = module.iam.instance_profile_arn
  ec2_instance_type    = var.ec2_instance_type
  asg_min_size         = var.asg_min_size
  asg_max_size         = var.asg_max_size
  asg_desired_capacity = var.asg_desired_capacity
}

module "lambda" {
  source          = "./modules/lambda"
  prefix          = var.prefix
  lambda_role_arn = module.iam.lambda_role_arn
  sns_topic_arn   = module.networking.sns_topic_arn
  asg_name        = module.compute.asg_name
  aws_region      = var.aws_region
}

module "eventbridge" {
  source      = "./modules/eventbridge"
  prefix      = var.prefix
  lambda_arn  = module.lambda.lambda_arn
  lambda_name = module.lambda.lambda_name
}

module "monitoring" {
  source               = "./modules/monitoring"
  prefix               = var.prefix
  sns_topic_arn        = module.networking.sns_topic_arn
  asg_name             = module.compute.asg_name
  remediation_rule_arn = module.eventbridge.remediation_rule_arn
}

module "devops_guru" {
  source        = "./modules/devops_guru"
  enable        = var.enable_devops_guru
  sns_topic_arn = module.networking.sns_topic_arn
}
