export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    fields?: { field: string; issue: string }[];
  };
};

export type CabinClass = "economy" | "premium_economy" | "business" | "first";

export type Profile = {
  full_name: string;
  phone: string | null;
  nationality: string | null;
  home_airport: string | null;
};

export type FrequentFlyer = { airline: string; number_masked: string };

export type Preferences = {
  preferred_airports: string[];
  preferred_airlines: string[];
  preferred_cabin: CabinClass | null;
  seat_preference: "window" | "aisle" | "no_preference" | null;
  meal_preference: string | null;
  frequent_flyer_programs: FrequentFlyer[];
  notes: string | null;
};

export type User = {
  id: string;
  email: string;
  role: "user" | "admin";
  created_at: string;
  profile: Profile;
  preferences: Preferences;
};

export type AuthResponse = {
  user: User;
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  csrf_token: string;
};
