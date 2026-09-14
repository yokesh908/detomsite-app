import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import './App.css'

const Home = lazy(() => import('./pages/Home').then(m => ({ default: m.Home })))
const Shops = lazy(() => import('./pages/Shops').then(m => ({ default: m.Shops })))
const ShopDetail = lazy(() => import('./pages/shop/ShopDetail').then(m => ({ default: m.ShopDetail })))
const CustomerDashboard = lazy(() => import('./pages/customer/CustomerDashboard').then(m => ({ default: m.CustomerDashboard })))
const FeedbackPage = lazy(() => import('./pages/customer/FeedbackPage').then(m => ({ default: m.FeedbackPage })))
const ShopkeeperDashboard = lazy(() => import('./pages/shopkeeper/ShopkeeperDashboard').then(m => ({ default: m.ShopkeeperDashboard })))
const AdminDashboard = lazy(() => import('./pages/admin/AdminDashboard').then(m => ({ default: m.AdminDashboard })))
const AuthPage = lazy(() => import('./pages/AuthPage').then(m => ({ default: m.AuthPage })))
const RoleGate = lazy(() => import('./components/RoleGate').then(m => ({ default: m.RoleGate })))
const MainLayout = lazy(() => import('./components/Layout').then(m => ({ default: m.MainLayout })))
const CartPage = lazy(() => import('./pages/CartPage').then(m => ({ default: m.CartPage })))
const PaymentPage = lazy(() => import('./pages/PaymentPage').then(m => ({ default: m.PaymentPage })))
const OrderResultPage = lazy(() => import('./pages/OrderResultPage').then(m => ({ default: m.OrderResultPage })))
const SupportPage = lazy(() => import('./pages/SupportPage').then(m => ({ default: m.SupportPage })))
const InstallPwaCard = lazy(() => import('./components/InstallPwaCard').then(m => ({ default: m.InstallPwaCard })))
const VendorRegister = lazy(() => import('./pages/vendor/VendorRegister').then(m => ({ default: m.VendorRegister })))
const AdminLogin = lazy(() => import('./pages/admin/AdminLogin').then(m => ({ default: m.AdminLogin })))

function PageSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-white">
      <div className="flex flex-col items-center gap-3">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-emerald-200 border-t-emerald-600" />
        <p className="text-sm font-medium text-gray-400">Loading...</p>
      </div>
    </div>
  )
}

/* ─── Portal Landing Page (student only) ─── */
function PortalLanding() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-800 text-white">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col items-center justify-center px-6 py-16 text-center">
        <span className="mb-6 flex h-20 w-20 items-center justify-center rounded-panel bg-gold/20 text-5xl font-black text-gold shadow-emerald-950/30 backdrop-blur-sm">D</span>
        <h1 className="text-5xl font-black tracking-tight sm:text-6xl lg:text-7xl">
          DETOMSITE
        </h1>
        <p className="mt-4 max-w-xl text-lg font-medium text-gold-light">
          Campus Food Ordering Platform — order from your campus kitchens
        </p>

        <div className="mt-12 w-full max-w-lg rounded-[28px] border border-gold-500/30 bg-white/5 p-8 backdrop-blur-sm">
          <span className="text-4xl">🎓</span>
          <h2 className="mt-4 text-2xl font-bold text-white">Student Portal</h2>
          <p className="mt-2 text-sm text-gold-light/90">Browse campus shops, place orders, and track deliveries.</p>
          <Link to="/auth"
            className="mt-6 flex items-center justify-center rounded-btn bg-gold px-6 py-3.5 text-base font-black text-white shadow-gold-lg transition-all hover:bg-gold-600 hover:-translate-y-0.5">
            Continue to Student Portal →
          </Link>
          <p className="mt-5 text-sm font-medium text-gold-light/80">
            Existing user?{' '}
            <Link to="/auth" className="font-bold text-white underline decoration-gold decoration-2 underline-offset-2 hover:text-gold">Sign In</Link>
          </p>
        </div>
      </div>
    </div>
  )
}

/* ─── Vendor Portal (Shopkeeper) Landing with PWA install ─── */
function VendorPortalLanding() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-white to-amber-50">
      <div className="mx-auto max-w-3xl px-4 py-12">
        <div className="mb-8 text-center">
          <span className="text-5xl">👨‍🍳</span>
          <h1 className="mt-3 text-3xl font-black text-primary-dark">Shopkeeper Portal</h1>
          <p className="mt-2 text-sm font-medium text-slate-500">Install the app and register your shop</p>
        </div>

        {/* PWA Install Card */}
        <div className="mb-8">
          <Suspense fallback={null}>
            <InstallPwaCard />
          </Suspense>
        </div>

        <div className="rounded-[28px] border border-emerald-100 bg-white p-6 shadow-[0_14px_42px_rgba(15,118,110,0.12)]">
          <h2 className="text-xl font-bold text-primary-dark">Already registered?</h2>
          <p className="mt-1 text-sm text-slate-500">Sign in to manage your shop and orders</p>
          <div className="mt-4 flex gap-3">
            <Link to="/vendor/register"
              className="flex-1 rounded-btn bg-gold px-5 py-2.5 text-center text-sm font-bold text-white transition-all hover:bg-gold">
              New Shopkeeper? Register
            </Link>
            <Link to="/auth"
              className="flex-1 rounded-btn border border-amber-200 bg-white px-5 py-2.5 text-center text-sm font-bold text-amber-700 transition-all hover:bg-amber-50">
              Sign In
            </Link>
          </div>
        </div>

        <Link to="/" className="mt-6 block text-center text-sm font-medium text-slate-400 hover:text-primary">
          ← Back to portals
        </Link>
      </div>
    </div>
  )
}

/* ─── 404 Page ─── */
function NotFound() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-white to-emerald-50 flex items-center justify-center px-6">
      <div className="max-w-md text-center">
        <div className="text-7xl mb-4">404</div>
        <h1 className="text-2xl font-bold text-primary-dark">Page not found</h1>
        <p className="mt-2 text-gray-500">The page you're looking for doesn't exist.</p>
        <Link to="/" className="mt-4 inline-block rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-gold-sm hover:bg-primary-dark">
          Go Home
        </Link>
      </div>
    </div>
  )
}

function App() {
  return (
    <Router>
      <Suspense fallback={<PageSpinner />}>
        <Routes>
          {/* Portal landing selector - no auth needed */}
          <Route path="/" element={<PortalLanding />} />
          <Route path="/admin" element={<AdminLogin />} />
          <Route path="/vendor" element={<VendorPortalLanding />} />
          <Route path="/vendor/register" element={<VendorRegister />} />
          <Route path="/admin/login" element={<AdminLogin />} />

          {/* Auth pages — unified login/signup for student & shopkeeper */}
          <Route path="/auth" element={<AuthPage />} />

          {/* All authenticated routes */}
          <Route path="/*" element={
            <RoleGate>
              <MainLayout>
                <Suspense fallback={<PageSpinner />}>
                  <Routes>
                    <Route path="/home" element={<Home />} />
                    <Route path="/shops" element={<Shops />} />
                    <Route path="/shop/:shopId" element={<ShopDetail />} />
                    <Route path="/cart" element={<CartPage />} />
                    <Route path="/payment" element={<PaymentPage />} />
                    <Route path="/order-result/:orderId" element={<OrderResultPage />} />
                    <Route path="/support" element={<SupportPage />} />
                    <Route path="/login" element={<AuthPage />} />
                    <Route path="/register" element={<AuthPage />} />
                    <Route path="/customer-dashboard" element={<CustomerDashboard />} />
                    <Route path="/feedback" element={<FeedbackPage />} />
                    <Route path="/shopkeeper-dashboard" element={<ShopkeeperDashboard />} />
                    <Route path="/admin-dashboard" element={<AdminDashboard />} />
                    <Route path="*" element={<NotFound />} />
                  </Routes>
                </Suspense>
              </MainLayout>
            </RoleGate>
          } />
        </Routes>
      </Suspense>
    </Router>
  )
}

export default App
