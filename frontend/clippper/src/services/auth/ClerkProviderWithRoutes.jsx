import { ClerkProvider } from "@clerk/react";
import { BrowserRouter } from 'react-router-dom';

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
const clerkAppearance = {
    elements: {
        modalBackdrop: {
            backdropFilter: 'blur(18px)',
        },
        modalContent: {
            width: 'min(96vw, 760px)',
            maxWidth: '760px',
        },
        cardBox: {
            width: '100%',
            maxWidth: '760px',
        },
        card: {
            width: '100%',
            minHeight: '620px',
            padding: '3rem',
        },
        headerTitle: {
            fontSize: '2rem',
        },
        headerSubtitle: {
            fontSize: '1rem',
        },
        formFieldInput: {
            minHeight: '3rem',
            fontSize: '1rem',
        },
        formButtonPrimary: {
            minHeight: '3rem',
            fontSize: '1rem',
        },
    },
};

if (!PUBLISHABLE_KEY){
    throw new Error('Clerk publishable key is missing.');
}


export default function ClerkProviderWithRoutes({ children }) {
    return (
        <ClerkProvider 
            publishableKey={PUBLISHABLE_KEY} 
            appearance={clerkAppearance}

            signInForceRedirectUrl="/dashboard"
            signUpForceRedirectUrl="/dashboard"
            signInFallbackRedirectUrl="/dashboard"
            signUpFallbackRedirectUrl="/dashboard"
            signInUrl="/sign-in"
            signUpUrl="/sign-up"
            
            // Important: Add this for better React Router integration
            routerPush={(to) => window.location.href = to}
            routerReplace={(to) => window.location.replace(to)}
        >
            <BrowserRouter>
                {children}
            </BrowserRouter>
        </ClerkProvider>
    )
}
