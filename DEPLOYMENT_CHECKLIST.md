# DETOMSITE - Production Deployment Checklist

## Pre-Deployment Verification

### Backend
- [ ] All environment variables configured in Vercel
  - [ ] MONGODB_URL (MongoDB Atlas)
  - [ ] REDIS_URL (Upstash Redis)
  - [ ] SECRET_KEY (changed from default)
  - [ ] RAZORPAY credentials
  - [ ] Cloudinary credentials
  - [ ] Sentry DSN
- [ ] Database migration scripts tested
- [ ] All tests passing (pytest coverage > 80%)
- [ ] Linting checks passing
- [ ] Security dependencies updated
- [ ] Error logging configured (Sentry)
- [ ] Database backup strategy configured
- [ ] Rate limiting configured
- [ ] CORS correctly configured for frontend domain
- [ ] JWT token expiry set appropriately

### Frontend
- [ ] Environment variables configured (.env.production)
  - [ ] VITE_API_URL points to production backend
  - [ ] VITE_RAZORPAY_KEY_ID (production key)
  - [ ] VITE_CLOUDINARY_CLOUD_NAME
- [ ] All build warnings resolved
- [ ] TypeScript compilation successful (no errors)
- [ ] Bundle size analyzed and optimized
- [ ] Service worker configured for PWA
- [ ] Manifest.json configured
- [ ] Browser title set to DETOMSITE
- [ ] Meta tags configured
- [ ] Error tracking integrated (Sentry)

### Infrastructure
- [ ] MongoDB Atlas configured
  - [ ] Backup enabled
  - [ ] Whitelist production IPs
  - [ ] Connection pooling configured
- [ ] Redis cache configured
  - [ ] TTL values set appropriately
  - [ ] Memory limits configured
- [ ] SSL/TLS certificates configured
- [ ] Domain DNS records configured
- [ ] CDN configured for static assets
- [ ] Email service configured (SMTP/SendGrid)
- [ ] Payment gateway tested in production mode
- [ ] Monitoring and alerting configured

### Security
- [ ] Default super admin credentials changed
- [ ] HTTPS enforced everywhere
- [ ] CSP headers configured
- [ ] CORS headers properly set
- [ ] Rate limiting enabled
- [ ] SQL injection prevention verified
- [ ] XSS protection enabled
- [ ] CSRF protection enabled
- [ ] Sensitive data not logged
- [ ] Dependencies scanned for vulnerabilities
- [ ] Security headers configured (X-Frame-Options, etc.)

### Performance
- [ ] Database indexes created
- [ ] Queries optimized
- [ ] Caching strategy implemented
- [ ] API response times acceptable (< 500ms)
- [ ] Frontend bundle size optimized (< 500KB gzipped)
- [ ] Images optimized and served from CDN
- [ ] Lazy loading implemented
- [ ] Database connection pooling configured

### Monitoring & Analytics
- [ ] Application logs configured
- [ ] Error tracking enabled (Sentry)
- [ ] Performance monitoring enabled (APM)
- [ ] User analytics configured
- [ ] Health check endpoint tested
- [ ] Alerting configured for critical errors
- [ ] Uptime monitoring configured

### Documentation
- [ ] API documentation updated
- [ ] Deployment guide created
- [ ] Runbook for common issues created
- [ ] Database schema documentation updated
- [ ] Environment variables documented
- [ ] Backup/restore procedures documented

### Testing
- [ ] E2E tests passing
- [ ] Performance tests passing
- [ ] Load testing completed (stress tested)
- [ ] Security testing completed
- [ ] Payment flow tested
- [ ] Email notifications tested

## Deployment Process

### Step 1: Backend Deployment
```bash
# Ensure all environment variables set in Vercel
# Push to main branch
git push origin main
# Vercel automatically deploys
```

### Step 2: Database Setup
```bash
# Run migrations if needed
# Seed initial data
python backend/scripts/seed.py
```

### Step 3: Frontend Deployment
```bash
# Frontend auto-deploys on push to main
# Verify frontend accesses correct backend API
```

### Step 4: Post-Deployment
- [ ] Test login flow end-to-end
- [ ] Test payment flow
- [ ] Verify all API endpoints responding
- [ ] Check error logs in Sentry
- [ ] Verify emails sending
- [ ] Monitor performance metrics
- [ ] Test on multiple browsers/devices

## Post-Deployment

### Day 1
- [ ] Monitor error rates closely
- [ ] Check user reports in support tickets
- [ ] Verify database backups running
- [ ] Test critical user journeys

### Week 1
- [ ] Review performance metrics
- [ ] Analyze user behavior
- [ ] Fix any reported bugs
- [ ] Optimize based on performance data

### Ongoing
- [ ] Regular security audits
- [ ] Dependency updates
- [ ] Database optimization
- [ ] Capacity planning
- [ ] Regular backup verification

## Rollback Plan

If critical issues occur:
```bash
# Revert to previous commit
git revert <commit_hash>
git push origin main
# Vercel auto-deploys previous version
```

## Support Contacts

- Database: MongoDB Atlas Support
- Cache: Upstash Support
- Payments: Razorpay Support
- Email: SendGrid/SMTP Support
- Deployment: Vercel Support

---

**Last Updated:** 2024
**Deployment Environment:** Production
