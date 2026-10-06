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

export type DocumentStatus = "queued" | "processing" | "extracted" | "failed" | "rejected";

export type DocumentType =
  | "passport"
  | "visa"
  | "flight_ticket"
  | "boarding_pass"
  | "hotel_booking"
  | "car_booking"
  | "insurance"
  | "itinerary"
  | "identity_document"
  | "other";

export type TravelDocument = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: DocumentStatus;
  error_code: string | null;
  error_message: string | null;
  document_type: DocumentType | null;
  type_confidence: number | null;
  analysis_method: "gemini" | "rules" | null;
  page_count: number | null;
  ocr_used: boolean;
  created_at: string;
  steps: { uploaded: boolean; scanned: boolean; text_extracted: boolean; fields_extracted: boolean };
};

export type ExtractedField = {
  field: string;
  label: string;
  value: string;
  masked: boolean;
  group: number;
  page: number | null;
  confidence: number | null;
  method: "gemini" | "rules" | "mrz";
};

export type TravelDocumentDetail = TravelDocument & { fields: ExtractedField[] };

export type AuthResponse = {
  user: User;
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  csrf_token: string;
};
