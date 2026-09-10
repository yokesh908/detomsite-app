"""
Setup guide for DETOMSITE development and deployment
"""
# DETOMSITE - Setup and Development Guide

## 📋 Prerequisites

- **Node.js**: v18 or higher
- **Python**: 3.12 or higher
- **Docker**: Latest version
- **Git**: For version control
- **MongoDB Atlas Account**: Cloud database
- **Razorpay Account**: Payment gateway (sandbox for testing)
- **Cloudinary Account**: Image storage

## 🚀 Quick Start

### 1. Clone Repository
```bash
git clone <repository-url>
cd detomsite
```

### 2. Setup Backend

#### Using Docker (Recommended)
```bash
# Start all services with Docker Compose
docker-compose up --build

# Backend will be available at http://localhost:8000
# Frontend will be available at http://localhost:5173
```

#### Manual Setup
```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Copy environment file
cp .env.example .env

# Update .env with your credentials:
# - MONGODB_URL
# - REDIS_URL
# - SECRET_KEY
# - RAZORPAY credentials

# Install dependencies
pip install -r requirements.txt

# Run application
python main.py
```

### 3. Setup Frontend

```bash
cd frontend

# Copy environment file
cp .env.example .env.local

# Update .env.local:
# VITE_API_URL=http://localhost:8000/api/v1

# Install dependencies
npm install

# Run development server
npm run dev

# Application will be available at http://localhost:5173
```

## 🔧 Configuration

### Backend Configuration (.env)

```env
# Database
MONGODB_URL=mongodb+srv://user:password@cluster.mongodb.net/detomsite
DATABASE_NAME=detomsite

# Redis Cache
REDIS_URL=redis://localhost:6379

# Local runnable database
USE_LOCAL_DB=True
LOCAL_DB_PATH=detomsite_local.db

# JWT Configuration
SECRET_KEY=your-super-secret-key-change-this
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Default Super Admin
DEFAULT_SUPER_ADMIN_EMAIL=admin@detomsite.local
DEFAULT_SUPER_ADMIN_PASSWORD=change-me-before-use-123

# Cloudinary (Image Storage)
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret

# Razorpay (Payments)
RAZORPAY_KEY_ID=your-key-id
RAZORPAY_KEY_SECRET=your-key-secret

# Monitoring
SENTRY_DSN=your-sentry-dsn

# Application
APP_NAME=DETOMSITE
APP_VERSION=3.1.0
DEBUG=False
HOST=0.0.0.0
PORT=8000

# CORS
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

### Frontend Configuration (.env.local)

```env
VITE_API_URL=http://localhost:8000/api/v1
VITE_APP_NAME=DETOMSITE
VITE_RAZORPAY_KEY_ID=your-razorpay-key
VITE_CLOUDINARY_CLOUD_NAME=your-cloud-name
```

## 📚 API Documentation

After starting the backend, visit:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI Schema**: http://localhost:8000/openapi.json

## 🗄️ Database

### MongoDB Collections

- **users** - All user accounts (customers, shopkeepers, admins, etc.)
- **campuses** - Campus/college configurations
- **shops** - Food shop listings
- **products** - Food items
- **categories** - Product categories
- **orders** - Customer orders
- **payments** - Payment records
- **reviews** - Product and shop reviews
- **notifications** - User notifications
- **tickets** - Support tickets
- **audit_logs** - Compliance logs
- **wallets** - User wallets
- **delivery_partners** - Delivery agent information
- **feature_flags** - Feature toggles
- **settings** - Platform settings

### Create Indexes

```python
# Run from backend directory
python -c "from app.core.database import *; import asyncio; asyncio.run(create_indexes())"
```

## 🧪 Testing

### Backend Tests
```bash
cd backend

# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test file
pytest tests/test_auth.py -v
```

### Frontend Tests
```bash
cd frontend

# Run tests
npm test

# Run with coverage
npm test -- --coverage

# Run in watch mode
npm test -- --watch
```

## 📦 Building for Production

### Backend
```bash
# Build Docker image
docker build -t detomsite-backend:latest ./backend

# Push to registry
docker tag detomsite-backend:latest your-registry/detomsite-backend:latest
docker push your-registry/detomsite-backend:latest
```

### Frontend
```bash
# Build production bundle
npm run build

# Preview production build
npm run preview

# Deploy to Vercel
vercel --prod
```

## 🔐 Security Best Practices

1. **Change Default Credentials**
   - Change default super admin password on first login
   - Update secret key in production

2. **Enable HTTPS**
   - Always use HTTPS in production
   - Obtain SSL certificate from Let's Encrypt

3. **Protect Environment Variables**
   - Never commit .env files
   - Use environment variable management service

4. **Rate Limiting**
   - Enable rate limiting on API
   - Implement DDoS protection

5. **Database Security**
   - Enable authentication on MongoDB
   - Use IP whitelist for database access
   - Regular backups

6. **API Security**
   - Implement CORS properly
   - Use CSRF tokens
   - Sanitize input
   - Implement request validation

## 🚢 Deployment

### Deploy to Vercel

#### Backend
```bash
cd backend
vercel --prod
# Configure environment variables in Vercel dashboard
```

#### Frontend
```bash
cd frontend
vercel --prod
# Configure environment variables in Vercel dashboard
```

### Deploy with Docker

```bash
# Build both images
docker-compose build --no-cache

# Deploy to your server
docker-compose -f docker-compose.prod.yml up -d
```

## 📊 Monitoring & Logging

### Application Health
- **Health Check**: GET /health
- **Metrics**: Available at /metrics (if Prometheus configured)

### Error Tracking
- **Sentry Integration**: Set SENTRY_DSN for automatic error reporting
- **Logs**: Check application logs in Vercel or Docker containers

### Performance Monitoring
- **Database**: Monitor query performance in MongoDB Atlas
- **Cache**: Monitor Redis usage in Upstash dashboard
- **API**: Use Vercel Analytics for API metrics

## 🐛 Troubleshooting

### MongoDB Connection Issues
```bash
# Test connection
mongosh "your-connection-string"
```

### Redis Connection Issues
```bash
# Test connection
redis-cli ping
```

### JWT Token Issues
- Verify SECRET_KEY is same across instances
- Check token expiration
- Verify CORS settings

### Payment Gateway Issues
- Test with Razorpay sandbox credentials first
- Check webhook signature verification
- Monitor payment logs

## 📚 Additional Resources

- **FastAPI Docs**: https://fastapi.tiangolo.com
- **React Docs**: https://react.dev
- **MongoDB Docs**: https://docs.mongodb.com
- **Razorpay Docs**: https://razorpay.com/docs
- **Vercel Docs**: https://vercel.com/docs

## 💬 Support

- **GitHub Issues**: Report bugs and feature requests
- **Email**: support@detomsite.com
- **Slack**: Join our community Slack workspace

## 📝 License

Proprietary - All rights reserved

---

**Last Updated**: 2024
**Version**: 3.1.0
