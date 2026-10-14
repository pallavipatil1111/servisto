// Servisto - shared JavaScript

// Send the CSRF token with every same-site POST made through fetch().
(function () {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (!meta || !window.fetch) return;
    const originalFetch = window.fetch.bind(window);
    window.fetch = function (resource, options = {}) {
        const url = new URL(typeof resource === 'string' ? resource : resource.url, window.location.href);
        const method = (options.method || 'GET').toUpperCase();
        if (url.origin === window.location.origin && method !== 'GET' && method !== 'HEAD') {
            const headers = new Headers(options.headers || {});
            headers.set('X-CSRFToken', meta.content);
            options = Object.assign({}, options, { headers, credentials: 'same-origin' });
        }
        return originalFetch(resource, options);
    };
})();

document.addEventListener('DOMContentLoaded', function() {
    // Initialize all components
    initFlashMessages();
    initFormValidations();
    initDropdowns();
    initModals();
    initRatingSystem();
    initSearchFilters();
    initBookingCalendar();
});

// Flash message auto-dismiss
function initFlashMessages() {
    const flashMessages = document.querySelectorAll('.alert');
    flashMessages.forEach(message => {
        setTimeout(() => {
            message.style.opacity = '0';
            message.style.transform = 'translateY(-10px)';
            setTimeout(() => message.remove(), 300);
        }, 5000);
    });
}

// Form validation enhancements
function initFormValidations() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const requiredFields = form.querySelectorAll('[required]');
            let isValid = true;

            requiredFields.forEach(field => {
                if (!field.value.trim()) {
                    isValid = false;
                    showFieldError(field, 'This field is required');
                } else {
                    clearFieldError(field);
                }
            });

            // Email validation
            const emailFields = form.querySelectorAll('input[type="email"]');
            emailFields.forEach(field => {
                if (field.value && !isValidEmail(field.value)) {
                    isValid = false;
                    showFieldError(field, 'Please enter a valid email address');
                }
            });

            // Password confirmation
            const password = form.querySelector('#password');
            const confirmPassword = form.querySelector('#confirm_password');
            if (password && confirmPassword && password.value !== confirmPassword.value) {
                isValid = false;
                showFieldError(confirmPassword, 'Passwords do not match');
            }

            if (!isValid) {
                e.preventDefault();
                // Scroll to first error
                const firstError = form.querySelector('.error-message');
                if (firstError) {
                    firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
        });
    });
}

// Email validation helper
function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

// Field error handling
function showFieldError(field, message) {
    clearFieldError(field);
    field.classList.add('border-red-500');
    
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message text-red-500 text-sm mt-1 flex items-center';
    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle mr-1"></i> ${message}`;
    
    field.parentNode.appendChild(errorDiv);
}

function clearFieldError(field) {
    field.classList.remove('border-red-500');
    const existingError = field.parentNode.querySelector('.error-message');
    if (existingError) {
        existingError.remove();
    }
}

// Dropdown menu functionality
function initDropdowns() {
    document.addEventListener('click', function(e) {
        // Close all dropdowns when clicking outside
        if (!e.target.closest('.group')) {
            document.querySelectorAll('.group .absolute').forEach(dropdown => {
                dropdown.classList.add('opacity-0', 'invisible');
            });
        }
    });
}

// Modal functionality
function initModals() {
    // Open modal
    window.openModal = function(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
            document.body.style.overflow = 'hidden';
        }
    };

    // Close modal
    window.closeModal = function(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            document.body.style.overflow = 'auto';
        }
    };

    // Close modal when clicking backdrop
    document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
        backdrop.addEventListener('click', function(e) {
            if (e.target === this) {
                const modal = this.closest('.modal');
                if (modal) {
                    closeModal(modal.id);
                }
            }
        });
    });

    // Close modal with Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal').forEach(modal => {
                if (!modal.classList.contains('hidden')) {
                    closeModal(modal.id);
                }
            });
        }
    });
}

// Rating system
function initRatingSystem() {
    const ratingContainers = document.querySelectorAll('.rating-input');
    
    ratingContainers.forEach(container => {
        const stars = container.querySelectorAll('.star');
        const hiddenInput = container.querySelector('input[type="hidden"]');
        
        stars.forEach((star, index) => {
            star.addEventListener('click', () => {
                const rating = index + 1;
                if (hiddenInput) {
                    hiddenInput.value = rating;
                }
                
                // Update star display
                stars.forEach((s, i) => {
                    if (i <= index) {
                        s.classList.add('filled', 'text-yellow-400');
                        s.classList.remove('text-gray-300');
                    } else {
                        s.classList.remove('filled', 'text-yellow-400');
                        s.classList.add('text-gray-300');
                    }
                });
            });
            
            star.addEventListener('mouseenter', () => {
                stars.forEach((s, i) => {
                    if (i <= index) {
                        s.classList.add('text-yellow-300');
                    } else {
                        s.classList.remove('text-yellow-300');
                    }
                });
            });
            
            star.addEventListener('mouseleave', () => {
                stars.forEach(s => {
                    s.classList.remove('text-yellow-300');
                });
                
                // Restore actual rating
                if (hiddenInput && hiddenInput.value) {
                    const currentRating = parseInt(hiddenInput.value);
                    stars.forEach((s, i) => {
                        if (i < currentRating) {
                            s.classList.add('text-yellow-400');
                        } else {
                            s.classList.remove('text-yellow-400');
                        }
                    });
                }
            });
        });
    });
}

// Search filters
function initSearchFilters() {
    const filterToggles = document.querySelectorAll('.filter-toggle');
    
    filterToggles.forEach(toggle => {
        toggle.addEventListener('click', function() {
            const filterSection = this.nextElementSibling;
            filterSection.classList.toggle('hidden');
            this.querySelector('i').classList.toggle('fa-chevron-down');
            this.querySelector('i').classList.toggle('fa-chevron-up');
        });
    });
}

// Booking calendar
function initBookingCalendar() {
    const dateInputs = document.querySelectorAll('input[type="date"]');
    
    dateInputs.forEach(input => {
        // Set min date to today
        // Today in the visitor's own time zone (toISOString() would use UTC).
        const now = new Date();
        const today = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().split('T')[0];
        if (!input.min || input.min < today) input.min = today;
        
        // Add some styling
        input.addEventListener('focus', function() {
            this.parentElement.classList.add('ring-2', 'ring-blue-500', 'ring-opacity-50');
        });
        
        input.addEventListener('blur', function() {
            this.parentElement.classList.remove('ring-2', 'ring-blue-500', 'ring-opacity-50');
        });
    });
}

// Utility functions
window.utils = {
    // Format currency
    formatCurrency: function(amount) {
        return new Intl.NumberFormat('en-IN', {
            style: 'currency',
            currency: 'INR',
            maximumFractionDigits: 2
        }).format(amount);
    },
    
    // Format date
    formatDate: function(dateString) {
        const options = { 
            year: 'numeric', 
            month: 'long', 
            day: 'numeric',
            weekday: 'long'
        };
        return new Date(dateString).toLocaleDateString('en-IN', options);
    },
    
    // Format time
    formatTime: function(timeString) {
        return timeString; // Add proper time formatting if needed
    },
    
    // Debounce function for search
    debounce: function(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },
    
    // Show loading state
    showLoading: function(button) {
        const originalText = button.innerHTML;
        button.innerHTML = '<div class="loading-spinner"></div> Loading...';
        button.disabled = true;
        return originalText;
    },
    
    // Hide loading state
    hideLoading: function(button, originalText) {
        button.innerHTML = originalText;
        button.disabled = false;
    }
};

// Service type icons mapping
window.serviceIcons = {
    'plumbing': 'fa-faucet',
    'cleaning': 'fa-broom',
    'painting': 'fa-paint-roller',
    'electrical': 'fa-bolt',
    'carpentry': 'fa-hammer',
    'gardening': 'fa-leaf',
    'moving': 'fa-truck-moving',
    'repair': 'fa-tools'
};

// Get service icon
function getServiceIcon(serviceType) {
    return window.serviceIcons[serviceType] || 'fa-tools';
}