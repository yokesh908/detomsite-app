/*
 * Common utility functions
 */
export const formatCurrency = (amount: number): string => {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
  }).format(amount);
};

export const formatDate = (date: string | Date): string => {
  return new Intl.DateTimeFormat("en-IN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(date));
};

export const formatTime = (date: string | Date): string => {
  return new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(date));
};

export const truncateText = (text: string, length: number): string => {
  if (text.length <= length) return text;
  return text.slice(0, length) + "...";
};

export const slugify = (text: string): string => {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
};

export const validateEmail = (email: string): boolean => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

export const validatePhone = (phone: string): boolean => {
  const phoneRegex = /^[0-9]{10}$/;
  return phoneRegex.test(phone.replace(/\D/g, ""));
};

export const getInitials = (firstName: string, lastName: string): string => {
  return `${firstName[0] || ""}${lastName[0] || ""}`.toUpperCase();
};

export const getRoleColor = (role: string): string => {
  const colors: Record<string, string> = {
    customer: "bg-blue-100 text-blue-800",
    shopkeeper: "bg-green-100 text-green-800",
    admin: "bg-purple-100 text-purple-800",
    super_admin: "bg-red-100 text-red-800",
    delivery_partner: "bg-orange-100 text-orange-800",
  };
  return colors[role] || "bg-gray-100 text-gray-800";
};

export const getStatusColor = (status: string): string => {
  const colors: Record<string, string> = {
    active: "bg-green-100 text-green-800",
    suspended: "bg-yellow-100 text-yellow-800",
    deleted: "bg-red-100 text-red-800",
    open: "bg-blue-100 text-blue-800",
    closed: "bg-gray-100 text-gray-800",
  };
  return colors[status] || "bg-gray-100 text-gray-800";
};
