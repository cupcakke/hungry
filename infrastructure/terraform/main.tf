terraform {
  required_version = ">= 1.5.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
  
  backend "s3" {
    bucket         = "payment-platform-terraform-state"
    key            = "infrastructure/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "payment-platform-terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Project     = "payment-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "eks_cluster_version" {
  description = "EKS cluster version"
  type        = string
  default     = "1.28"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.r6g.xlarge"
}

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.r6g.large"
}

data "aws_caller_identity" "current" {}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  
  tags = {
    Name = "payment-platform-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  
  tags = {
    Name = "payment-platform-igw"
  }
}

resource "aws_eip" "nat" {
  count  = length(var.availability_zones)
  domain = "vpc"
  
  tags = {
    Name = "payment-platform-nat-eip-${count.index + 1}"
  }
}

resource "aws_subnet" "public" {
  count                   = length(var.availability_zones)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true
  
  tags = {
    Name = "payment-platform-public-${count.index + 1}"
    Type = "public"
  }
}

resource "aws_subnet" "private" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = var.availability_zones[count.index]
  
  tags = {
    Name = "payment-platform-private-${count.index + 1}"
    Type = "private"
  }
}

resource "aws_subnet" "database" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 20)
  availability_zone = var.availability_zones[count.index]
  
  tags = {
    Name = "payment-platform-database-${count.index + 1}"
    Type = "database"
  }
}

resource "aws_nat_gateway" "main" {
  count         = length(var.availability_zones)
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  
  tags = {
    Name = "payment-platform-nat-${count.index + 1}"
  }
  
  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  
  tags = {
    Name = "payment-platform-public-rt"
  }
}

resource "aws_route_table" "private" {
  count  = length(var.availability_zones)
  vpc_id = aws_vpc.main.id
  
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }
  
  tags = {
    Name = "payment-platform-private-rt-${count.index + 1}"
  }
}

resource "aws_route_table_association" "public" {
  count          = length(var.availability_zones)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = length(var.availability_zones)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

resource "aws_security_group" "eks_cluster" {
  name        = "payment-platform-eks-cluster-sg"
  description = "Security group for EKS cluster"
  vpc_id      = aws_vpc.main.id
  
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "payment-platform-eks-cluster-sg"
  }
}

resource "aws_security_group" "rds" {
  name        = "payment-platform-rds-sg"
  description = "Security group for RDS PostgreSQL"
  vpc_id      = aws_vpc.main.id
  
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.eks_cluster.id]
  }
  
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    cidr_blocks     = [var.vpc_cidr]
  }
  
  tags = {
    Name = "payment-platform-rds-sg"
  }
}

resource "aws_security_group" "redis" {
  name        = "payment-platform-redis-sg"
  description = "Security group for ElastiCache Redis"
  vpc_id      = aws_vpc.main.id
  
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.eks_cluster.id]
  }
  
  tags = {
    Name = "payment-platform-redis-sg"
  }
}

resource "aws_db_subnet_group" "main" {
  name       = "payment-platform-db-subnet-group"
  subnet_ids = aws_subnet.database[*].id
  
  tags = {
    Name = "payment-platform-db-subnet-group"
  }
}

resource "aws_db_parameter_group" "main" {
  family = "postgres15"
  name   = "payment-platform-postgres-params"
  
  parameter {
    name  = "log_connections"
    value = "1"
  }
  
  parameter {
    name  = "log_disconnections"
    value = "1"
  }
  
  parameter {
    name  = "log_duration"
    value = "1"
  }
}

resource "aws_kms_key" "main" {
  description             = "Payment Platform KMS key"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  
  tags = {
    Name = "payment-platform-kms-key"
  }
}

resource "aws_rds_cluster" "main" {
  engine                    = "aurora-postgresql"
  engine_version            = "15.4"
  database_name             = "payment_platform"
  master_username           = "admin"
  master_password           = random_password.db_master.result
  db_subnet_group_name      = aws_db_subnet_group.main.name
  vpc_security_group_ids    = [aws_security_group.rds.id]
  storage_encrypted         = true
  kms_key_id                = aws_kms_key.main.arn
  backup_retention_period   = 30
  preferred_backup_window   = "03:00-04:00"
  preferred_maintenance_window = "sun:04:00-sun:05:00"
  skip_final_snapshot       = false
  final_snapshot_identifier = "payment-platform-final-snapshot"
  deletion_protection       = true
  
  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 16
  }
  
  tags = {
    Name = "payment-platform-aurora-cluster"
  }
}

resource "aws_rds_cluster_instance" "main" {
  count              = 2
  identifier         = "payment-platform-${count.index + 1}"
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version
  
  tags = {
    Name = "payment-platform-aurora-${count.index + 1}"
  }
}

resource "random_password" "db_master" {
  length  = 32
  special = true
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "payment-platform-redis-subnet-group"
  subnet_ids = aws_subnet.private[*].id
  
  tags = {
    Name = "payment-platform-redis-subnet-group"
  }
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id       = "payment-platform-redis"
  description                = "Payment Platform Redis cluster"
  node_type                  = var.redis_node_type
  num_cache_clusters         = 3
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.redis.id]
  automatic_failover_enabled = true
  multi_az_enabled           = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result
  engine                     = "redis"
  engine_version             = "7.0"
  parameter_group_name       = "default.redis7"
  snapshot_retention_limit   = 7
  snapshot_window            = "03:00-04:00"
  
  tags = {
    Name = "payment-platform-redis"
  }
}

resource "random_password" "redis_auth" {
  length  = 32
  special = false
}

resource "aws_eks_cluster" "main" {
  name     = "payment-platform-eks"
  version  = var.eks_cluster_version
  role_arn = aws_iam_role.eks_cluster.arn
  
  vpc_config {
    subnet_ids              = concat(aws_subnet.public[*].id, aws_subnet.private[*].id)
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = ["0.0.0.0/0"]
    security_group_ids      = [aws_security_group.eks_cluster.id]
  }
  
  encryption_config {
    provider {
      key_arn = aws_kms_key.main.arn
    }
    resources = ["secrets"]
  }
  
  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  
  tags = {
    Name = "payment-platform-eks"
  }
}

resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "payment-platform-workers"
  node_role_arn   = aws_iam_role.eks_nodes.arn
  subnet_ids      = aws_subnet.private[*].id
  
  scaling_config {
    desired_size = 3
    max_size     = 10
    min_size     = 3
  }
  
  update_config {
    max_unavailable_percentage = 33
  }
  
  instance_types = ["m6i.xlarge"]
  capacity_type  = "ON_DEMAND"
  
  labels = {
    Environment = var.environment
  }
  
  tags = {
    Name = "payment-platform-eks-node-group"
  }
  
  depends_on = [
    aws_iam_role_policy_attachment.eks_nodes_policy,
    aws_iam_role_policy_attachment.eks_cni_policy,
    aws_iam_role_policy_attachment.eks_container_registry
  ]
}

resource "aws_iam_role" "eks_cluster" {
  name = "payment-platform-eks-cluster-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = {
        Service = "eks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.eks_cluster.name
}

resource "aws_iam_role" "eks_nodes" {
  name = "payment-platform-eks-nodes-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_nodes_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_iam_role_policy_attachment" "eks_cni_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_iam_role_policy_attachment" "eks_container_registry" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_s3_bucket" "files" {
  bucket = "payment-platform-files-${random_id.bucket_suffix.hex}"
  
  tags = {
    Name = "payment-platform-files"
  }
}

resource "aws_s3_bucket_versioning" "files" {
  bucket = aws_s3_bucket.files.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "files" {
  bucket = aws_s3_bucket.files.id
  
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.main.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "files" {
  bucket = aws_s3_bucket.files.id
  
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "backups" {
  bucket = "payment-platform-backups-${random_id.bucket_suffix.hex}"
  
  tags = {
    Name = "payment-platform-backups"
  }
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  
  rule {
    id     = "transition-to-glacier"
    status = "Enabled"
    
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    
    expiration {
      days = 365
    }
  }
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_ecr_repository" "api" {
  name                 = "payment-platform/api"
  image_tag_mutability = "MUTABLE"
  
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }
  
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "worker" {
  name                 = "payment-platform/worker"
  image_tag_mutability = "MUTABLE"
  
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }
  
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "webhook" {
  name                 = "payment-platform/webhook"
  image_tag_mutability = "MUTABLE"
  
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }
  
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "admin" {
  name                 = "payment-platform/admin"
  image_tag_mutability = "MUTABLE"
  
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }
  
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_cloudwatch_log_group" "eks" {
  name              = "/aws/eks/payment-platform/cluster"
  retention_in_days = 30
}

resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "payment-platform/database"
  recovery_window_in_days = 7
  
  tags = {
    Name = "payment-platform-db-credentials"
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = "admin"
    password = random_password.db_master.result
    host     = aws_rds_cluster.main.endpoint
    port     = 5432
    database = "payment_platform"
  })
}

resource "aws_secretsmanager_secret" "app_secrets" {
  name                    = "payment-platform/secrets"
  recovery_window_in_days = 7
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "eks_cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}

output "eks_cluster_name" {
  value = aws_eks_cluster.main.name
}

output "rds_endpoint" {
  value = aws_rds_cluster.main.endpoint
}

output "redis_endpoint" {
  value = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "s3_bucket_files" {
  value = aws_s3_bucket.files.bucket
}

output "s3_bucket_backups" {
  value = aws_s3_bucket.backups.bucket
}

output "ecr_repositories" {
  value = {
    api     = aws_ecr_repository.api.repository_url
    worker  = aws_ecr_repository.worker.repository_url
    webhook = aws_ecr_repository.webhook.repository_url
    admin   = aws_ecr_repository.admin.repository_url
  }
}
