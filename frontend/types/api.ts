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

export type DocumentStatus =
  | "queued"
  | "processing"
  | "extracted"
  | "ready"
  | "failed"
  | "rejected";

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
  steps: {
    uploaded: boolean;
    scanned: boolean;
    text_extracted: boolean;
    fields_extracted: boolean;
    indexed: boolean;
  };
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

// ---------------------------------------------------------------- assistant

export type MessageType =
  | "TEXT"
  | "DOCUMENT_INFO"
  | "FLIGHT_RESULTS"
  | "HOTEL_RESULTS"
  | "BOOKING_CONFIRMATION"
  | "BOOKING_STATUS"
  | "CONFIRMATION_REQUEST"
  | "ERROR";

export type Source = {
  type: "document" | "policy";
  title: string;
  document_id: string | null;
  page: number | null;
  section: string | null;
};

type OfferBase = {
  offer_id: string;
  provider: string;
  test_booking: boolean;
  title: string;
  price: number;
  currency: string;
  start_date: string;
  end_date: string;
};

export type FlightOffer = OfferBase & {
  type: "flight_offer";
  airline: string;
  flight_number: string;
  origin: string;
  destination: string;
  departure: string;
  arrival: string;
  duration_minutes: number;
  stops: number;
  cabin: string | null;
  fare: string;
  baggage: string;
};

export type HotelOffer = OfferBase & {
  type: "hotel_offer";
  hotel_name: string;
  address: string;
  stars: number;
  room_type: string;
  nights: number;
  refundable: boolean;
};

export type CarOffer = OfferBase & {
  type: "car_offer";
  company: string;
  car_class: string;
  model: string;
  pickup_location: string;
  days: number;
};

export type ExcursionOffer = OfferBase & {
  type: "excursion_offer";
  city: string;
  duration_hours: number;
  participants: number;
};

export type Offer = FlightOffer | HotelOffer | CarOffer | ExcursionOffer;

export type BookingKind = "flight" | "hotel" | "car" | "excursion";
export type BookingStatus =
  | "booking"
  | "confirmed"
  | "modification_requested"
  | "modified"
  | "cancellation_requested"
  | "cancelled"
  | "failed"
  | "expired";

export type Refund = { refund_amount: number; fee: number; currency: string };

export type BookingCard = {
  type: "booking";
  booking_id: string;
  kind: BookingKind;
  status: BookingStatus;
  provider: string;
  test_booking: boolean;
  confirmation_number: string | null;
  title: string | null;
  start_date: string | null;
  end_date: string | null;
  total_amount: number;
  currency: string;
  travellers: string[];
  refund: Refund | null;
  payment_status: string | null;
};

export type ConfirmationSummary = {
  // book
  kind?: BookingKind;
  title?: string;
  price?: number;
  currency?: string;
  start_date?: string;
  end_date?: string;
  travellers?: string[];
  test_booking?: boolean;
  previous_price?: number;
  // cancel / modify
  booking?: BookingCard;
  refund?: Refund;
  new?: { title: string; start_date: string; end_date: string; price: number; currency: string };
  price_difference?: number;
};

export type ConfirmationCard = {
  type: "confirmation";
  confirmation_id: string;
  action: "book" | "cancel" | "modify";
  summary: ConfirmationSummary;
  expires_at: string;
};

export type ChatCard = Offer | BookingCard | ConfirmationCard;

export type AssistantMessage = {
  type: MessageType;
  text: string;
  sources: Source[];
  cards: ChatCard[];
};

export type ChatResponse = {
  conversation_id: string;
  message: AssistantMessage;
  agent: string;
};

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  type: MessageType | null;
  sources: Source[];
  cards: ChatCard[];
  agent: string | null;
  created_at: string;
};

export type Conversation = {
  id: string;
  title: string;
  active_agent: string | null;
  created_at: string;
  updated_at: string;
};

export type ConversationDetail = Conversation & { messages: ChatMessage[] };

// ---------------------------------------------------------------- bookings

export type Booking = {
  id: string;
  kind: BookingKind;
  status: BookingStatus;
  provider: string;
  test_booking: boolean;
  confirmation_number: string | null;
  title: string | null;
  start_date: string | null;
  end_date: string | null;
  total_amount: number;
  currency: string;
  details: Record<string, unknown> & {
    travellers?: string[];
    refund?: Refund;
    payment?: { status: string; session_id: string; test: boolean };
    modified_from?: { start_date: string; price: number };
  };
  created_at: string;
  updated_at: string;
};

export type ConfirmationOut = {
  confirmation_id: string;
  action: ConfirmationCard["action"];
  summary: ConfirmationSummary;
  expires_at: string;
};

export type ConfirmResponse = {
  confirmation_id: string;
  status: string;
  message: AssistantMessage;
  booking: Booking | null;
};
