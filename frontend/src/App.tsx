import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom'
import './App.css'
import { Home } from './pages/Home'
import { Shops } from './pages/Shops'
import { ShopDetail } from './pages/shop/ShopDetail'
import { CustomerDashboard } from './pages/customer/CustomerDashboard'
import { FeedbackPage } from './pages/customer/FeedbackPage'
import { ShopkeeperDashboard } from './pages/shopkeeper/ShopkeeperDashboard'
import { AdminDashboard } from './pages/admin/AdminDashboard'
import { AuthPage } from './pages/AuthPage'
import { RoleGate } from './components/RoleGate'
import { MainLayout } from './components/Layout'
import { CartPage } from './pages/CartPage'
import { PaymentPage } from './pages/PaymentPage'
import { OrderResultPage } from './pages/OrderResultPage'
import { SupportPage } from './pages/SupportPage'
import { InstallPwaCard } from './components/InstallPwaCard'
import { VendorRegister } from './pages/vendor/VendorRegister'
import { AdminLogin } from './pages/admin/AdminLogin'

/* ─── Portal Landing Page ─── */
function PortalLanding() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-800 text-white">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col items-center justify-center px-6 py-16 text-center">
        <span className="mb-6 flex h-20 w-20 items-center justify-center rounded-panel bg-gold-light/15 text-5xl font-black text-gold shadow-2xl shadow-emerald-950/30 backdrop-blur-sm">D</span>
        <h1 className="text-5xl font-black tracking-tight sm:text-6xl lg:text-7xl">
          DETOMSITE
        </h1>
        <p className="mt-4 max-w-xl text-lg font-medium text-primary/50/80">
          Campus Food Ordering Platform — Choose your portal below
        </p>

        <div className="mt-12 grid gap-5 sm:grid-cols-3">
          {/* Student */}            <Link to="/auth"
            className="group rounded-[28px] border border-white/10 bg-white/5 p-6 text-left backdrop-blur-sm transition-all hover:bg-white/10 hover:-translate-y-1 hover:shadow-2xl">
            <span className="text-4xl">🎓</span>
            <h2 className="mt-4 text-xl font-bold text-white">Student Portal</h2>
            <p className="mt-2 text-sm text-primary/50/60">Browse shops, place orders, track deliveries.</p>
            <div className="mt-4 inline-flex rounded-btn bg-primary px-4 py-2 text-sm font-bold text-white transition-all group-hover:bg-primary">
              Register →
            </div>
          </Link>

          {/* Shopkeeper */}            <Link to="/vendor/register"
            className="group rounded-[28px] border border-amber-300/20 bg-gold-light/5 p-6 text-left backdrop-blur-sm transition-all hover:bg-gold-light/10 hover:-translate-y-1 hover:shadow-2xl">
            <span className="text-4xl">👨‍🍳</span>
            <h2 className="mt-4 text-xl font-bold text-white">Shopkeeper Portal</h2>
            <p className="mt-2 text-sm text-primary/50/60">Register your shop, manage orders, install mobile app.</p>
            <div className="mt-4 inline-flex rounded-btn bg-gold px-4 py-2 text-sm font-bold text-white transition-all group-hover:bg-gold">
              Register Shop →
            </div>
          </Link>

          {/* Admin */}
          <Link to="/admin"
            className="group rounded-[28px] border border-white/10 bg-white/5 p-6 text-left backdrop-blur-sm transition-all hover:bg-white/10 hover:-translate-y-1 hover:shadow-2xl">
            <span className="text-4xl">⚙️</span>
            <h2 className="mt-4 text-xl font-bold text-white">Admin Portal</h2>
            <p className="mt-2 text-sm text-primary/50/60">Approve shops, monitor orders, manage platform.</p>
            <div className="mt-4 inline-flex rounded-btn bg-primary px-4 py-2 text-sm font-bold text-white transition-all group-hover:bg-primary">
              Admin Login →
            </div>
          </Link>
        </div>

        <p className="mt-10 text-sm font-medium text-primary/50/40">
          Existing users{' '}
          <Link to="/auth" className="font-bold text-gold hover:text-gold">Sign In</Link>
        </p>
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
          <InstallPwaCard />
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
            </MainLayout>
          </RoleGate>
        } />
      </Routes>
    </Router>
  )
}

export default App
