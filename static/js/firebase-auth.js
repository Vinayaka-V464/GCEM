// ============================================
// Firebase Authentication for Paper Generator
// Email/Password + Google Sign-in + Email Verification
// ============================================

// Firebase config is fetched from the server (env vars) — never hardcoded here.
let auth = null;
let googleProvider = null;

async function initFirebase() {
    if (typeof firebase === 'undefined') {
        console.error('Firebase SDK not loaded');
        return;
    }
    try {
        const response = await fetch('/api/firebase-config', {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const firebaseConfig = await response.json();
        firebase.initializeApp(firebaseConfig);
        auth = firebase.auth();
        googleProvider = new firebase.auth.GoogleAuthProvider();
        console.log('Firebase initialized');
    } catch (err) {
        console.error('Failed to load Firebase config:', err);
    }
}

// Google Sign-In
async function signInWithGoogle() {
    try {
        const result = await auth.signInWithPopup(googleProvider);
        const user = result.user;
        const idToken = await user.getIdToken();

        return {
            success: true,
            user: {
                uid: user.uid,
                email: user.email,
                displayName: user.displayName,
                photoURL: user.photoURL,
                emailVerified: user.emailVerified,
                idToken: idToken
            }
        };
    } catch (error) {
        console.error('Google sign-in error:', error);
        return { success: false, message: error.message };
    }
}

// Email/Password Sign In
async function signInWithEmail(email, password) {
    try {
        const result = await auth.signInWithEmailAndPassword(email, password);
        const user = result.user;

        // Check if email is verified
        if (!user.emailVerified) {
            return {
                success: false,
                needsVerification: true,
                message: 'Please verify your email before signing in. Check your inbox for the verification link.'
            };
        }

        const idToken = await user.getIdToken();

        return {
            success: true,
            user: {
                uid: user.uid,
                email: user.email,
                displayName: user.displayName,
                emailVerified: user.emailVerified,
                idToken: idToken
            }
        };
    } catch (error) {
        console.error('Email sign-in error:', error);
        let message = error.message;
        if (error.code === 'auth/user-not-found') {
            message = 'No account found with this email. Please sign up first.';
        } else if (error.code === 'auth/wrong-password') {
            message = 'Incorrect password. Please try again.';
        } else if (error.code === 'auth/invalid-email') {
            message = 'Invalid email address.';
        } else if (error.code === 'auth/invalid-credential') {
            message = 'Invalid email or password. Please try again.';
        }
        return { success: false, message: message };
    }
}

// Email/Password Sign Up with Email Verification
async function signUpWithEmail(email, password) {
    try {
        const result = await auth.createUserWithEmailAndPassword(email, password);
        const user = result.user;

        // Send verification email
        await user.sendEmailVerification({
            url: window.location.origin + '/login?verified=true',
            handleCodeInApp: false
        });

        const idToken = await user.getIdToken();

        return {
            success: true,
            verificationSent: true,
            user: {
                uid: user.uid,
                email: user.email,
                emailVerified: false,
                idToken: idToken
            },
            message: 'Verification email sent! Please check your inbox and click the link to verify your email.'
        };
    } catch (error) {
        console.error('Email sign-up error:', error);
        let message = error.message;
        if (error.code === 'auth/email-already-in-use') {
            message = 'An account with this email already exists. Please login instead.';
        } else if (error.code === 'auth/weak-password') {
            message = 'Password should be at least 6 characters.';
        } else if (error.code === 'auth/invalid-email') {
            message = 'Invalid email address.';
        }
        return { success: false, message: message };
    }
}

// Resend Verification Email
async function resendVerificationEmail() {
    try {
        const user = auth.currentUser;
        if (user && !user.emailVerified) {
            await user.sendEmailVerification({
                url: window.location.origin + '/login?verified=true',
                handleCodeInApp: false
            });
            return { success: true, message: 'Verification email sent! Check your inbox.' };
        } else {
            return { success: false, message: 'No user to verify or already verified.' };
        }
    } catch (error) {
        console.error('Resend verification error:', error);
        if (error.code === 'auth/too-many-requests') {
            return { success: false, message: 'Too many requests. Please wait a few minutes before trying again.' };
        }
        return { success: false, message: error.message };
    }
}

// Check if current user's email is verified
async function checkEmailVerified() {
    try {
        const user = auth.currentUser;
        if (user) {
            await user.reload(); // Refresh user data
            return user.emailVerified;
        }
        return false;
    } catch (error) {
        console.error('Check verification error:', error);
        return false;
    }
}

// Sign Out
async function signOut() {
    try {
        await auth.signOut();
        window.location.href = '/login';
    } catch (error) {
        console.error('Sign out error:', error);
    }
}

// Get current user
function getCurrentUser() {
    return auth ? auth.currentUser : null;
}

// Send user data to backend
async function sendUserToBackend(userData, role, name = '', extraData = {}) {
    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                uid: userData.uid,
                email: userData.email || '',
                name: name || userData.displayName || '',
                role: role,
                idToken: userData.idToken,
                photoURL: userData.photoURL || '',
                emailVerified: userData.emailVerified || false,
                ...extraData
            })
        });

        const result = await response.json();
        return result;
    } catch (error) {
        console.error('Error registering user:', error);
        return { success: false, message: error.message };
    }
}

// Verify session with backend
async function verifySession(idToken, userData = null) {
    try {
        const response = await fetch('/api/auth/verify', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                idToken: idToken,
                uid: userData?.uid || null,
                email: userData?.email || null
            })
        });

        const result = await response.json();
        return result;
    } catch (error) {
        console.error('Error verifying session:', error);
        return { success: false };
    }
}

// UI Helper Functions
function showError(message) {
    const alertEl = document.getElementById('alert');
    if (alertEl) {
        alertEl.className = 'alert alert-error';
        alertEl.textContent = message;
        alertEl.classList.remove('hidden');
        setTimeout(() => alertEl.classList.add('hidden'), 6000);
    }
}

function showSuccess(message) {
    const alertEl = document.getElementById('alert');
    if (alertEl) {
        alertEl.className = 'alert alert-success';
        alertEl.textContent = message;
        alertEl.classList.remove('hidden');
    }
}

function showInfo(message) {
    const alertEl = document.getElementById('alert');
    if (alertEl) {
        alertEl.className = 'alert alert-info';
        alertEl.textContent = message;
        alertEl.classList.remove('hidden');
    }
}

function showLoading(buttonEl, show = true) {
    if (show) {
        buttonEl.disabled = true;
        buttonEl.dataset.originalText = buttonEl.innerHTML;
        buttonEl.innerHTML = '<span class="spinner"></span> Please wait...';
    } else {
        buttonEl.disabled = false;
        buttonEl.innerHTML = buttonEl.dataset.originalText || 'Submit';
    }
}
