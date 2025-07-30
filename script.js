// script.js (Frontend)
const API_BASE_URL = 'http://localhost:3000/api/v1';

// Global variables
let currentUser = null;
let userBalance = 0;

// Hàm gọi API chung
async function callApi(endpoint, method = 'GET', body = null, requiresAuth = true) {
  const headers = {
    'Content-Type': 'application/json',
  };
  
  if (requiresAuth) {
    const token = localStorage.getItem('token');
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }
  
  const options = {
    method,
    headers,
  };
  
  if (body) {
    options.body = JSON.stringify(body);
  }
  
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
    const data = await response.json();
    
    if (!response.ok) {
      throw new Error(data.message || 'Something went wrong');
    }
    
    return data;
  } catch (error) {
    console.error('API call failed:', error);
    throw error;
  }
}

// Format price function
window.formatPrice = function(price) {
  return price.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
};

// Show toast notification
window.showToast = function(message, type = 'success') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <div class="toast-message">${message}</div>
    <button class="toast-close">&times;</button>
  `;
  document.body.appendChild(toast);
  
  setTimeout(function() {
    toast.classList.add('visible');
  }, 100);
  
  setTimeout(function() {
    toast.classList.remove('visible');
    setTimeout(function() {
      toast.remove();
    }, 300);
  }, 3000);
  
  toast.querySelector('.toast-close').addEventListener('click', function() {
    toast.classList.remove('visible');
    setTimeout(function() {
      toast.remove();
    }, 300);
  });
};

// Authentication functions
async function authenticate(email, password) {
  try {
    const data = await callApi('/users/login', 'POST', { email, password }, false);
    localStorage.setItem('token', data.token);
    return data.data.user;
  } catch (error) {
    console.error('Login failed:', error);
    return null;
  }
}

async function registerUser(name, email, password, passwordConfirm) {
  try {
    const data = await callApi('/users/signup', 'POST', { 
      name, 
      email, 
      password, 
      passwordConfirm 
    }, false);
    localStorage.setItem('token', data.token);
    return data.data.user;
  } catch (error) {
    console.error('Registration failed:', error);
    throw error;
  }
}

// Product functions
async function loadProducts() {
  try {
    const data = await callApi('/products');
    return data.data.products;
  } catch (error) {
    console.error('Failed to load products:', error);
    return [];
  }
}

async function getProductDetails(productId) {
  try {
    const data = await callApi(`/products/${productId}`);
    return data.data.product;
  } catch (error) {
    console.error('Failed to get product details:', error);
    return null;
  }
}

async function getRelatedProducts(productId) {
  try {
    const data = await callApi(`/products/related/${productId}`);
    return data.data.products;
  } catch (error) {
    console.error('Failed to get related products:', error);
    return [];
  }
}

// User functions
async function getUserBalance() {
  try {
    const data = await callApi('/users/me/balance');
    return data.data.balance;
  } catch (error) {
    console.error('Failed to get user balance:', error);
    return 0;
  }
}

async function processDeposit(cardNumber, cardSerial, cardType, amount) {
  try {
    const data = await callApi('/users/deposit', 'POST', {
      cardNumber,
      cardSerial,
      cardType,
      amount
    });
    return data;
  } catch (error) {
    console.error('Deposit failed:', error);
    throw error;
  }
}

// Cập nhật UI sau khi đăng nhập
async function updateUIAfterLogin() {
  try {
    const userData = await callApi('/users/me');
    const balanceData = await callApi('/users/me/balance');
    
    currentUser = userData.data.user;
    userBalance = balanceData.data.balance;
    
    const loginButton = document.getElementById('loginButton');
    if (!loginButton) return;

    loginButton.outerHTML = `
      <div class="user-dropdown" id="userDropdown">
        <div class="user-avatar">${currentUser.avatarText || currentUser.name.charAt(0).toUpperCase()}</div>
        <span class="user-name">${currentUser.name}</span>
        <div class="dropdown-menu">
          <a href="account.html" class="dropdown-item" id="accountButton">
            <i class="fas fa-user"></i>
            <span>Tài khoản</span>
          </a>
          <div class="dropdown-item coming-soon-action">
            <i class="fas fa-heart"></i>
            <span>Yêu thích</span>
          </div>
          <div class="dropdown-item coming-soon-action">
            <i class="fas fa-shopping-cart"></i>
            <span>Giỏ hàng</span>
          </div>
          <div class="dropdown-divider"></div>
          <div class="dropdown-item" id="logoutButton">
            <i class="fas fa-sign-out-alt"></i>
            <span>Đăng xuất</span>
          </div>
        </div>
      </div>
    `;

    document.getElementById('logoutButton').addEventListener('click', logoutUser);
    document.getElementById('accountButton').addEventListener('click', showAccountModal);
    
    document.querySelectorAll('.coming-soon-action').forEach(item => {
      item.addEventListener('click', showComingSoonModal);
    });
    
  } catch (error) {
    console.error('Failed to update UI after login:', error);
  }
}

// Hàm xử lý nạp tiền
async function processDeposit() {
  const form = document.getElementById('depositForm');
  const cardNumber = document.getElementById('cardNumber').value.trim();
  const cardSerial = document.getElementById('cardSerial').value.trim();
  const cardAmount = document.getElementById('cardAmount').value;
  const cardType = document.querySelector('.card-type.selected')?.getAttribute('data-type');
  const submitBtn = form.querySelector('.btn-submit');
  
  // Validate form
  let isValid = true;
  
  if (!cardNumber) {
    showError(document.getElementById('cardNumber'), 'Vui lòng nhập mã thẻ');
    isValid = false;
  } else if (cardNumber.length < 10 || !/^\d+$/.test(cardNumber)) {
    showError(document.getElementById('cardNumber'), 'Mã thẻ phải có ít nhất 10 chữ số');
    isValid = false;
  }
  
  if (!cardSerial) {
    showError(document.getElementById('cardSerial'), 'Vui lòng nhập số serial');
    isValid = false;
  } else if (cardSerial.length < 5 || !/^\d+$/.test(cardSerial)) {
    showError(document.getElementById('cardSerial'), 'Số serial phải có ít nhất 5 chữ số');
    isValid = false;
  }
  
  if (!cardAmount) {
    showError(document.getElementById('cardAmount'), 'Vui lòng chọn mệnh giá');
    isValid = false;
  }
  
  if (!cardType) {
    showToast('Vui lòng chọn loại thẻ', 'error');
    isValid = false;
  }
  
  if (!isValid) return;
  
  // Show loading state
  submitBtn.classList.add('loading');
  submitBtn.disabled = true;
  
  try {
    const response = await callApi('/users/deposit', 'POST', {
      cardNumber,
      cardSerial,
      cardType,
      amount: parseInt(cardAmount)
    });
    
    userBalance = response.data.user.balance;
    
    showToast(`Nạp thành công ${formatPrice(cardAmount)}đ vào tài khoản`, 'success');
    
    setTimeout(() => {
      const depositModal = document.getElementById('depositModal');
      depositModal.classList.remove('show');
      setTimeout(() => {
        depositModal.style.display = 'none';
        document.body.style.overflow = 'auto';
        form.reset();
        updateBalanceDisplays(userBalance);
      }, 300);
    }, 1000);
    
  } catch (error) {
    showToast(error.message || 'Có lỗi xảy ra khi xử lý thẻ. Vui lòng thử lại', 'error');
  } finally {
    submitBtn.classList.remove('loading');
    submitBtn.disabled = false;
  }
}

// Cập nhật hiển thị số dư
function updateBalanceDisplays(balance) {
  const accountBalanceElement = document.getElementById('accountBalance');
  if (accountBalanceElement) {
    accountBalanceElement.textContent = formatPrice(balance);
  }
  
  const balanceAmountElement = document.getElementById('balanceAmount');
  if (balanceAmountElement) {
    balanceAmountElement.textContent = formatPrice(balance) + 'đ';
  }
  
  updateDepositHistory();
}

// Cập nhật lịch sử nạp tiền
async function updateDepositHistory() {
  const depositHistoryElement = document.getElementById('depositHistory');
  if (!depositHistoryElement) return;
  
  try {
    const transactionsData = await callApi('/users/transactions');
    const transactions = transactionsData.data.transactions;
    
    if (!transactions || transactions.length === 0) {
      depositHistoryElement.innerHTML = '<div class="empty-history">Chưa có giao dịch nạp tiền</div>';
      return;
    }
    
    depositHistoryElement.innerHTML = transactions.filter(t => t.type === 'deposit').map(transaction => `
      <div class="deposit-item">
        <div>
          <div class="deposit-amount">+${formatPrice(transaction.amount)}đ</div>
          <div class="deposit-date">${new Date(transaction.createdAt).toLocaleString('vi-VN')}</div>
          <div class="deposit-info">
            <span>Thẻ ${transaction.cardType}</span>
            <span>••••${transaction.cardNumber.slice(-4)}</span>
          </div>
        </div>
        <div class="deposit-status success">
          Thành công
        </div>
      </div>
    `).join('');
  } catch (error) {
    console.error('Failed to load transaction history:', error);
    depositHistoryElement.innerHTML = '<div class="empty-history">Lỗi khi tải lịch sử giao dịch</div>';
  }
}

// Hàm hiển thị modal tài khoản
async function showAccountModal() {
  const accountModal = document.getElementById('accountModal');
  const accountAvatar = document.getElementById('accountAvatar');
  const accountName = document.getElementById('accountName');
  const accountEmail = document.getElementById('accountEmail');
  const accountBalance = document.getElementById('accountBalance');
  const accountId = document.getElementById('accountId');
  
  try {
    const userData = await callApi('/users/me');
    const balanceData = await callApi('/users/me/balance');
    
    currentUser = userData.data.user;
    userBalance = balanceData.data.balance;
    
    accountAvatar.textContent = currentUser.avatarText || currentUser.name.charAt(0).toUpperCase();
    accountName.textContent = currentUser.name;
    accountEmail.textContent = currentUser.email;
    accountBalance.textContent = formatPrice(userBalance);
    
    if (accountId) {
      accountId.textContent = `ID: ${currentUser._id}`;
    }
    
    updateDepositHistory();
  } catch (error) {
    console.error('Failed to load account data:', error);
    showToast('Không thể tải thông tin tài khoản', 'error');
  }
  
  accountModal.style.display = 'flex';
  document.body.style.overflow = 'hidden';
  
  setTimeout(() => {
    accountModal.classList.add('show');
  }, 10);
}

// Hàm đăng xuất
async function logoutUser() {
  try {
    await callApi('/users/logout');
    
    localStorage.removeItem('token');
    localStorage.removeItem('rememberMe');
    
    currentUser = null;
    userBalance = 0;
    
    const userDropdown = document.querySelector('.user-dropdown');
    if (userDropdown) {
      userDropdown.outerHTML = `
        <button class="btn btn-primary" id="loginButton">
          <i class="fas fa-user"></i>
          <span>Đăng Nhập</span>
        </button>
      `;
    }
    
    initAuthModal();
    showToast('Bạn đã đăng xuất thành công', 'success');
    
    if (window.location.pathname.includes('account.html')) {
      window.location.href = 'index.html';
    }
  } catch (error) {
    console.error('Logout failed:', error);
    showToast('Đăng xuất thất bại', 'error');
  }
}

// Khởi tạo modal xác thực
function initAuthModal() {
  const authModal = document.getElementById('authModal');
  const forgotModal = document.getElementById('forgotPasswordModal');
  const loginButton = document.getElementById('loginButton');
  const closeModal = document.getElementById('closeModal');
  const closeForgotModal = document.getElementById('closeForgotModal');
  const forgotPasswordLink = document.getElementById('forgotPassword');
  const modalTabs = document.querySelectorAll('.modal-tab');
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  const forgotPasswordForm = document.getElementById('forgotPasswordForm');
  
  // Password toggle functionality
  function initPasswordToggles() {
    document.querySelectorAll('.password-toggle').forEach(toggle => {
      toggle.addEventListener('click', function() {
        const input = this.previousElementSibling;
        const isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';
        this.innerHTML = isPassword ? '<i class="fas fa-eye-slash"></i>' : '<i class="fas fa-eye"></i>';
      });
    });
  }
  
  // Form validation
  function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(String(email).toLowerCase());
  }
  
  function validatePassword(password) {
    return password.length >= 6;
  }
  
  function showError(input, message) {
    const formGroup = input.closest('.form-group');
    formGroup.classList.add('has-error');
    const errorElement = formGroup.querySelector('.error-message');
    if (errorElement) {
      errorElement.textContent = message;
      errorElement.style.display = 'block';
    }
  }
  
  function clearError(input) {
    const formGroup = input.closest('.form-group');
    formGroup.classList.remove('has-error');
    const errorElement = formGroup.querySelector('.error-message');
    if (errorElement) {
      errorElement.style.display = 'none';
    }
  }
  
  // Initialize form validation
  function initFormValidation() {
    document.getElementById('loginEmail').addEventListener('blur', function() {
      if (!this.value) {
        showError(this, 'Vui lòng nhập email');
      } else if (!validateEmail(this.value)) {
        showError(this, 'Email không hợp lệ');
      } else {
        clearError(this);
      }
    });
    
    document.getElementById('loginPassword').addEventListener('blur', function() {
      if (!this.value) {
        showError(this, 'Vui lòng nhập mật khẩu');
      } else if (!validatePassword(this.value)) {
        showError(this, 'Mật khẩu phải có ít nhất 6 ký tự');
      } else {
        clearError(this);
      }
    });
    
    document.getElementById('registerName').addEventListener('blur', function() {
      if (!this.value) {
        showError(this, 'Vui lòng nhập họ tên');
      } else {
        clearError(this);
      }
    });
    
    document.getElementById('registerEmail').addEventListener('blur', function() {
      if (!this.value) {
        showError(this, 'Vui lòng nhập email');
      } else if (!validateEmail(this.value)) {
        showError(this, 'Email không hợp lệ');
      } else {
        clearError(this);
      }
    });
    
    document.getElementById('registerPassword').addEventListener('blur', function() {
      if (!this.value) {
        showError(this, 'Vui lòng nhập mật khẩu');
      } else if (!validatePassword(this.value)) {
        showError(this, 'Mật khẩu phải có ít nhất 6 ký tự');
      } else {
        clearError(this);
      }
    });
    
    document.getElementById('registerConfirmPassword').addEventListener('blur', function() {
      const password = document.getElementById('registerPassword').value;
      if (!this.value) {
        showError(this, 'Vui lòng nhập lại mật khẩu');
      } else if (this.value !== password) {
        showError(this, 'Mật khẩu không khớp');
      } else {
        clearError(this);
      }
    });
    
    document.getElementById('forgotEmail').addEventListener('blur', function() {
      if (!this.value) {
        showError(this, 'Vui lòng nhập email');
      } else if (!validateEmail(this.value)) {
        showError(this, 'Email không hợp lệ');
      } else {
        clearError(this);
      }
    });
  }
  
  // Open auth modal
  if (loginButton) {
    loginButton.addEventListener('click', function() {
      authModal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
      setTimeout(() => {
        authModal.classList.add('show');
      }, 10);
      document.querySelector('.modal-tab[data-tab="login"]').click();
    });
  }
  
  // Close modals
  closeModal.addEventListener('click', function() {
    authModal.classList.remove('show');
    setTimeout(() => {
      authModal.style.display = 'none';
      document.body.style.overflow = 'auto';
      loginForm.reset();
      registerForm.reset();
    }, 300);
  });
  
  closeForgotModal.addEventListener('click', function() {
    forgotModal.classList.remove('show');
    setTimeout(() => {
      forgotModal.style.display = 'none';
      document.body.style.overflow = 'auto';
      forgotPasswordForm.reset();
    }, 300);
  });
  
  // Close when clicking outside
  window.addEventListener('click', function(event) {
    if (event.target === authModal) {
      authModal.classList.remove('show');
      setTimeout(() => {
        authModal.style.display = 'none';
        document.body.style.overflow = 'auto';
        loginForm.reset();
        registerForm.reset();
      }, 300);
    }
    if (event.target === forgotModal) {
      forgotModal.classList.remove('show');
      setTimeout(() => {
        forgotModal.style.display = 'none';
        document.body.style.overflow = 'auto';
        forgotPasswordForm.reset();
      }, 300);
    }
  });
  
  // Switch between login and register tabs
  modalTabs.forEach(tab => {
    tab.addEventListener('click', function() {
      modalTabs.forEach(t => t.classList.remove('active'));
      this.classList.add('active');
      
      const tabName = this.getAttribute('data-tab');
      document.querySelectorAll('.modal-form').forEach(form => {
        form.classList.remove('active');
      });
      document.getElementById(`${tabName}Form`).classList.add('active');
    });
  });
  
  // Open forgot password modal
  forgotPasswordLink.addEventListener('click', function(e) {
    e.preventDefault();
    authModal.style.display = 'none';
    forgotModal.style.display = 'flex';
    setTimeout(() => {
      forgotModal.classList.add('show');
    }, 10);
  });
  
  // Switch to login from forgot password
  document.querySelectorAll('.switch-to-login').forEach(link => {
    link.addEventListener('click', function(e) {
      e.preventDefault();
      forgotModal.classList.remove('show');
      setTimeout(() => {
        forgotModal.style.display = 'none';
        authModal.style.display = 'flex';
        setTimeout(() => {
          authModal.classList.add('show');
        }, 10);
        document.querySelector('.modal-tab[data-tab="login"]').click();
      }, 300);
    });
  });
  
  // Switch to register from login
  document.querySelectorAll('.switch-to-register').forEach(link => {
    link.addEventListener('click', function(e) {
      e.preventDefault();
      document.querySelector('.modal-tab[data-tab="register"]').click();
    });
  });
  
  // Login form submission
  loginForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    const rememberMe = document.getElementById('rememberMe').checked;
    const submitBtn = this.querySelector('.btn-submit');
    
    // Validate form
    let isValid = true;
    if (!email) {
      showError(document.getElementById('loginEmail'), 'Vui lòng nhập email');
      isValid = false;
    } else if (!validateEmail(email)) {
      showError(document.getElementById('loginEmail'), 'Email không hợp lệ');
      isValid = false;
    }
    
    if (!password) {
      showError(document.getElementById('loginPassword'), 'Vui lòng nhập mật khẩu');
      isValid = false;
    } else if (!validatePassword(password)) {
      showError(document.getElementById('loginPassword'), 'Mật khẩu phải có ít nhất 6 ký tự');
      isValid = false;
    }
    
    if (!isValid) return;
    
    submitBtn.classList.add('loading');
    submitBtn.disabled = true;
    
    try {
      const user = await authenticate(email, password);
      
      if (!user) {
        showError(document.getElementById('loginPassword'), 'Email hoặc mật khẩu không đúng');
        return;
      }
      
      if (rememberMe) {
        localStorage.setItem('rememberMe', 'true');
      } else {
        localStorage.removeItem('rememberMe');
      }
      
      const successHTML = `
        <div class="login-success">
          <div class="login-success-icon">
            <i class="fas fa-check-circle"></i>
          </div>
          <h3 class="login-success-message">Đăng nhập thành công!</h3>
          <p>Chào mừng ${user.name} trở lại</p>
        </div>
      `;
      
      authModal.querySelector('.modal-content').insertAdjacentHTML('beforeend', successHTML);
      document.querySelector('.modal-form.active').style.display = 'none';
      document.querySelector('.social-login').style.display = 'none';
      document.querySelector('.login-success').style.display = 'block';
      
      setTimeout(function() {
        authModal.style.display = 'none';
        document.body.style.overflow = 'auto';
        updateUIAfterLogin();
        
        const successElement = document.querySelector('.login-success');
        if (successElement) {
          successElement.remove();
        }
        
        document.querySelector('.modal-form.active').style.display = 'block';
        document.querySelector('.social-login').style.display = 'block';
      }, 1500);
      
    } catch (error) {
      showError(document.getElementById('loginPassword'), error.message || 'Đăng nhập thất bại');
    } finally {
      submitBtn.classList.remove('loading');
      submitBtn.disabled = false;
    }
  });
  
  // Register form submission
  registerForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    const name = document.getElementById('registerName').value;
    const email = document.getElementById('registerEmail').value;
    const password = document.getElementById('registerPassword').value;
    const confirmPassword = document.getElementById('registerConfirmPassword').value;
    const submitBtn = this.querySelector('.btn-submit');

    // Validate form
    let isValid = true;
    if (!name) {
      showError(document.getElementById('registerName'), 'Vui lòng nhập họ tên');
      isValid = false;
    }
    
    if (!email) {
      showError(document.getElementById('registerEmail'), 'Vui lòng nhập email');
      isValid = false;
    } else if (!validateEmail(email)) {
      showError(document.getElementById('registerEmail'), 'Email không hợp lệ');
      isValid = false;
    }
    
    if (!password) {
      showError(document.getElementById('registerPassword'), 'Vui lòng nhập mật khẩu');
      isValid = false;
    } else if (!validatePassword(password)) {
      showError(document.getElementById('registerPassword'), 'Mật khẩu phải có ít nhất 6 ký tự');
      isValid = false;
    }
    
    if (!confirmPassword) {
      showError(document.getElementById('registerConfirmPassword'), 'Vui lòng nhập lại mật khẩu');
      isValid = false;
    } else if (confirmPassword !== password) {
      showError(document.getElementById('registerConfirmPassword'), 'Mật khẩu không khớp');
      isValid = false;
    }
    
    if (!isValid) return;
    
    submitBtn.classList.add('loading');
    submitBtn.disabled = true;
    
    try {
      await registerUser(name, email, password, confirmPassword);
      
      showToast('Đăng ký thành công!', 'success');
      
      setTimeout(function() {
        modalTabs.forEach(t => t.classList.remove('active'));
        document.querySelector('.modal-tab[data-tab="login"]').classList.add('active');
        
        document.querySelectorAll('.modal-form').forEach(form => {
          form.classList.remove('active');
        });
        loginForm.classList.add('active');
        
        document.getElementById('loginEmail').value = email;
        registerForm.reset();
      }, 1000);
    } catch (error) {
      showError(document.getElementById('registerEmail'), error.message || 'Đăng ký thất bại');
    } finally {
      submitBtn.classList.remove('loading');
      submitBtn.disabled = false;
    }
  });
  
  // Forgot password form submission
  forgotPasswordForm.addEventListener('submit', function(e) {
    e.preventDefault();
    const email = document.getElementById('forgotEmail').value;
    const submitBtn = this.querySelector('.btn-submit');
    
    if (!email) {
      showError(document.getElementById('forgotEmail'), 'Vui lòng nhập email');
      return;
    } else if (!validateEmail(email)) {
      showError(document.getElementById('forgotEmail'), 'Email không hợp lệ');
      return;
    }
    
    submitBtn.classList.add('loading');
    submitBtn.disabled = true;
    
    setTimeout(function() {
      submitBtn.classList.remove('loading');
      submitBtn.disabled = false;
      
      showToast('Yêu cầu đặt lại mật khẩu đã được gửi đến email của bạn!', 'success');
      
      setTimeout(function() {
        forgotModal.style.display = 'none';
        document.body.style.overflow = 'auto';
        forgotPasswordForm.reset();
      }, 1000);
    }, 1500);
  });
  
  // Social login buttons
  document.querySelectorAll('.social-button').forEach(button => {
    button.addEventListener('click', function() {
      const provider = this.classList.contains('facebook') ? 'Facebook' : 'Google';
      const submitBtn = this;
      
      submitBtn.innerHTML = '<div class="spinner"></div>';
      
      setTimeout(function() {
        const randomNum = Math.floor(Math.random() * 1000);
        const socialUser = {
          name: `User${randomNum}`,
          email: `user${randomNum}@${provider.toLowerCase()}.com`,
          avatarText: 'U'
        };
        
        currentUser = socialUser;
        updateUIAfterLogin();
        
        authModal.style.display = 'none';
        document.body.style.overflow = 'auto';
        
        showToast(`Đăng nhập bằng ${provider} thành công`, 'success');
        
        submitBtn.innerHTML = provider === 'Facebook' 
          ? '<i class="fab fa-facebook-f"></i>' 
          : '<i class="fab fa-google"></i>';
      }, 1500);
    });
  });
  
  initPasswordToggles();
  initFormValidation();
}

// Khởi tạo modal tài khoản
function initAccountModal() {
  const accountModal = document.getElementById('accountModal');
  const closeAccountModal = document.getElementById('closeAccountModal');
  const depositAction = document.getElementById('depositAction');
  const logoutAccountBtn = document.getElementById('logoutAccountBtn');
  const changePasswordBtn = document.getElementById('changePasswordBtn');
  
  closeAccountModal.addEventListener('click', function() {
    accountModal.classList.remove('show');
    setTimeout(() => {
      accountModal.style.display = 'none';
      document.body.style.overflow = 'auto';
    }, 300);
  });
  
  depositAction.addEventListener('click', function() {
    accountModal.classList.remove('show');
    setTimeout(() => {
      accountModal.style.display = 'none';
      showDepositModal();
    }, 300);
  });
  
  logoutAccountBtn.addEventListener('click', function() {
    accountModal.classList.remove('show');
    setTimeout(() => {
      accountModal.style.display = 'none';
      document.body.style.overflow = 'auto';
      logoutUser();
    }, 300);
  });
  
  if (changePasswordBtn) {
    changePasswordBtn.addEventListener('click', function() {
      showChangePasswordModal();
    });
  }
  
  accountModal.addEventListener('click', function(e) {
    if (e.target === accountModal) {
      accountModal.classList.remove('show');
      setTimeout(() => {
        accountModal.style.display = 'none';
        document.body.style.overflow = 'auto';
      }, 300);
    }
  });
}

// Hiển thị modal nạp tiền
function showDepositModal() {
  const depositModal = document.getElementById('depositModal');
  
  depositModal.style.display = 'flex';
  document.body.style.overflow = 'hidden';
  
  setTimeout(() => {
    depositModal.classList.add('show');
  }, 10);
  
  document.querySelectorAll('.card-type').forEach(card => {
    card.addEventListener('click', function() {
      document.querySelectorAll('.card-type').forEach(c => c.classList.remove('selected'));
      this.classList.add('selected');
    });
  });
  
  document.getElementById('depositForm').addEventListener('submit', function(e) {
    e.preventDefault();
    processDeposit();
  });
  
  document.getElementById('closeDepositModal').addEventListener('click', function() {
    depositModal.classList.remove('show');
    setTimeout(() => {
      depositModal.style.display = 'none';
      document.body.style.overflow = 'auto';
      document.getElementById('depositForm').reset();
    }, 300);
  });
  
  depositModal.addEventListener('click', function(e) {
    if (e.target === depositModal) {
      depositModal.classList.remove('show');
      setTimeout(() => {
        depositModal.style.display = 'none';
        document.body.style.overflow = 'auto';
        document.getElementById('depositForm').reset();
      }, 300);
    }
  });
}

// Hiển thị modal đổi mật khẩu
function showChangePasswordModal() {
  const modal = document.getElementById('changePasswordModal');
  modal.style.display = 'flex';
  document.body.style.overflow = 'hidden';
  
  setTimeout(() => {
    modal.classList.add('show');
  }, 10);
  
  document.getElementById('changePasswordForm').onsubmit = async function(e) {
    e.preventDefault();
    
    const currentPassword = document.getElementById('currentPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const confirmNewPassword = document.getElementById('confirmNewPassword').value;
    
    if (newPassword !== confirmNewPassword) {
      showToast("Mật khẩu mới không khớp", "error");
      return;
    }
    
    if (newPassword.length < 6) {
      showToast("Mật khẩu phải có ít nhất 6 ký tự", "error");
      return;
    }
    
    try {
      const response = await callApi('/users/updateMyPassword', 'PATCH', {
        passwordCurrent: currentPassword,
        password: newPassword,
        passwordConfirm: confirmNewPassword
      });
      
      showToast("Đổi mật khẩu thành công", "success");
      
      setTimeout(() => {
        modal.classList.remove('show');
        setTimeout(() => {
          modal.style.display = 'none';
          document.body.style.overflow = 'auto';
          this.reset();
        }, 300);
      }, 1000);
    } catch (error) {
      showToast(error.message || "Đổi mật khẩu thất bại", "error");
    }
  };
  
  document.getElementById('closeChangePasswordModal').addEventListener('click', function() {
    modal.classList.remove('show');
    setTimeout(() => {
      modal.style.display = 'none';
      document.body.style.overflow = 'auto';
      document.getElementById('changePasswordForm').reset();
    }, 300);
  });
  
  modal.addEventListener('click', function(e) {
    if (e.target === modal) {
      modal.classList.remove('show');
      setTimeout(() => {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
        document.getElementById('changePasswordForm').reset();
      }, 300);
    }
  });
}

// Hiển thị modal coming soon
function showComingSoonModal() {
  const comingSoonModal = document.getElementById('comingSoonModal');
  
  comingSoonModal.style.display = 'flex';
  document.body.style.overflow = 'hidden';
  
  setTimeout(() => {
    comingSoonModal.classList.add('show');
  }, 10);
  
  document.getElementById('closeComingSoonModal').addEventListener('click', function() {
    comingSoonModal.classList.remove('show');
    setTimeout(() => {
      comingSoonModal.style.display = 'none';
      document.body.style.overflow = 'auto';
    }, 300);
  });
  
  comingSoonModal.addEventListener('click', function(e) {
    if (e.target === comingSoonModal) {
      comingSoonModal.classList.remove('show');
      setTimeout(() => {
        comingSoonModal.style.display = 'none';
        document.body.style.overflow = 'auto';
      }, 300);
    }
  });
}

// Back to Top Button
function initBackToTopButton() {
  const backToTopBtn = document.getElementById('backToTop');
  
  if (backToTopBtn) {
    window.addEventListener('scroll', function() {
      if (window.pageYOffset > 300) {
        backToTopBtn.classList.add('visible');
      } else {
        backToTopBtn.classList.remove('visible');
      }
    });
    
    backToTopBtn.addEventListener('click', function() {
      window.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    });
  }
}

// Khởi tạo khi DOM được tải
document.addEventListener('DOMContentLoaded', function() {
  initBackToTopButton();
  
  // Kiểm tra đăng nhập khi tải trang
  if (localStorage.getItem('rememberMe') === 'true' && localStorage.getItem('token')) {
    updateUIAfterLogin();
  }
  
  // Khởi tạo modal xác thực nếu có nút đăng nhập
  if (document.getElementById('loginButton')) {
    initAuthModal();
  }
  
  // Khởi tạo modal tài khoản nếu có
  if (document.getElementById('accountModal')) {
    initAccountModal();
  }
  
  // Tải sản phẩm nếu ở trang chủ
  if (document.getElementById('productsContainer')) {
    loadProducts();
  }
  
  // Khởi tạo nút lọc sản phẩm
  const filterButtons = document.querySelectorAll('.filter-btn');
  if (filterButtons.length > 0) {
    filterButtons.forEach(button => {
      button.addEventListener('click', filterProducts);
    });
    
    const resetFilterBtn = document.getElementById('resetFilterBtn');
    if (resetFilterBtn) {
      resetFilterBtn.addEventListener('click', resetFilters);
    }
  }
});

// Hàm lọc sản phẩm (giữ nguyên từ code gốc)
function filterProducts() {
  console.log('Filtering products...');
}

// Hàm reset bộ lọc (giữ nguyên từ code gốc)
function resetFilters() {
  console.log('Resetting filters...');
}