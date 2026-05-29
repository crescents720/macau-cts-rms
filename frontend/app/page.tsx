"use client";

import {
  CalendarDays,
  Check,
  Hotel,
  Pencil,
  Plus,
  RefreshCw,
  SearchCheck,
  Store,
  Trash2,
  X
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

type HotelRecord = {
  id: string;
  name: string;
  district: string;
};

type RoomType = {
  id: string;
  hotel_id: string;
  code: string;
  source_id: number;
  name: string;
  base_rate: number;
};

type Recommendation = {
  stay_date: string;
  hotel_id: string;
  room_type_id: string;
  day_type: string;
  base_rate_source: string;
  current_rate: number;
  recommended_rate: number;
  historical_average_rate: number | null;
  historical_comparison_date: string | null;
  event_premium_rate: number;
  event_adjustment_amount: number;
  event_names: string[];
  event_logic: string[];
  competitor_market_rate: number | null;
  competitor_adjustment_amount: number;
  competitor_logic: string[];
  change_percent: number;
  confidence: number;
  reasons: string[];
};

type ChartPoint = {
  date: string;
  currentRate: number;
  recommendedRate: number;
  historicalAverageRate: number | null;
  confidence: number;
  reason: string;
  source: Recommendation;
};

type RecommendationDotProps = {
  cx?: number;
  cy?: number;
  payload?: ChartPoint;
};

type EventHotelImpact = {
  hotel_id: string;
  distance_km: number | null;
  final_weight: number;
  logic: string | null;
};

type ExternalEventRecord = {
  id: number;
  name: string;
  event_type: string;
  start_date: string;
  end_date: string;
  venue_id: string | null;
  venue_name: string | null;
  source_name: string | null;
  source_url: string | null;
  confidence_score: number;
  impact_level: string;
  base_weight: number;
  status: string;
  notes: string | null;
  hotel_impacts: EventHotelImpact[];
};

type VenueRecord = {
  id: string;
  name: string;
  district: string;
  latitude: number;
  longitude: number;
  default_impact_radius_km: number;
};

type EventFormState = {
  name: string;
  event_type: string;
  start_date: string;
  end_date: string;
  venue_id: string;
  source_name: string;
  source_url: string;
  confidence_score: number;
  impact_level: string;
  base_weight: number;
  status: string;
  notes: string;
};

type EventCollectionCandidate = {
  name: string;
  event_type: string;
  start_date: string;
  end_date: string;
  venue_id: string | null;
  venue_name: string | null;
  source_name: string;
  source_url: string | null;
  confidence_score: number;
  impact_level: string;
  base_weight: number;
  notes: string | null;
};

type CompetitorHotelRecord = {
  id: string;
  name: string;
  district: string;
  ctrip_hotel_id: string | null;
  ctrip_url: string | null;
  active: boolean;
  room_type_count: number;
};

type CompetitorRoomTypeRecord = {
  id: number;
  competitor_hotel_id: string;
  competitor_hotel_name: string;
  name: string;
  ctrip_room_id: string | null;
  normalized_name: string | null;
  active: boolean;
};

type CompetitorMappingRecord = {
  id: number;
  hotel_id: string;
  room_type_id: string;
  room_type_name: string;
  competitor_room_type_id: number;
  competitor_hotel_id: string;
  competitor_hotel_name: string;
  competitor_room_type_name: string;
  priority: number;
  weight: number;
  notes: string | null;
};

type CompetitorRateObservationRecord = {
  id: number;
  competitor_room_type_id: number;
  competitor_hotel_name: string;
  competitor_room_type_name: string;
  stay_date: string;
  price: number;
  currency: string;
  source: string;
  source_url: string | null;
  collected_at: string;
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8003";

const predictionWindows = [
  { label: "\u672a\u6765\u4e00\u5468", value: 7 },
  { label: "\u672a\u676515\u5929", value: 15 },
  { label: "\u672a\u676530\u5929", value: 30 },
  { label: "\u672a\u676560\u5929", value: 60 },
  { label: "\u672a\u676590\u5929", value: 90 }
];

const eventTypes = ["concert", "grand_prix", "exhibition", "festival", "sports", "other"];
const impactLevels = ["minor", "medium", "major", "citywide"];
const eventStatuses = ["candidate", "confirmed", "rejected", "expired"];

function todayString() {
  return new Date().toISOString().slice(0, 10);
}

function defaultEventForm(): EventFormState {
  const today = todayString();
  return {
    name: "",
    event_type: "concert",
    start_date: today,
    end_date: today,
    venue_id: "",
    source_name: "Manual",
    source_url: "",
    confidence_score: 0.75,
    impact_level: "medium",
    base_weight: 0.08,
    status: "candidate",
    notes: ""
  };
}

const copy = {
  appSubtitle: "\u6536\u76ca\u7ba1\u7406\u539f\u578b",
  nav: "\u4e3b\u5bfc\u822a",
  ninetyDayAdvice: "90\u5929\u5efa\u8bae",
  trend: "\u4ef7\u683c\u8d70\u52bf",
  eventReview: "\u4e8b\u4ef6\u5ba1\u6838",
  competitorPricing: "\u7ade\u54c1\u4ef7\u683c",
  competitorHint: "\u914d\u7f6e\u6211\u65b9\u623f\u578b\u4e0e\u7ade\u54c1\u623f\u578b\u7684\u6620\u5c04\uff0c\u5e76\u7ba1\u7406\u7ade\u54c1\u4ef7\u683c\u89c2\u6d4b",
  competitorHotels: "\u7ade\u54c1\u9152\u5e97",
  competitorRoomTypes: "\u7ade\u54c1\u623f\u578b",
  addCompetitorRoom: "\u65b0\u589e\u7ade\u54c1\u623f\u578b",
  addMapping: "\u6dfb\u52a0\u6620\u5c04",
  mappings: "\u623f\u578b\u6620\u5c04",
  rateObservations: "\u4ef7\u683c\u89c2\u6d4b",
  addRate: "\u8bb0\u5f55\u4ef7\u683c",
  competitorHotel: "\u7ade\u54c1\u9152\u5e97",
  competitorRoom: "\u7ade\u54c1\u623f\u578b",
  stayDate: "\u5165\u4f4f\u65e5\u671f",
  price: "\u4ef7\u683c",
  source: "\u6765\u6e90",
  noMappings: "\u5f53\u524d\u623f\u578b\u8fd8\u6ca1\u6709\u7ade\u54c1\u6620\u5c04",
  noRates: "\u6682\u65e0\u7ade\u54c1\u4ef7\u683c\u89c2\u6d4b",
  eventReviewHint: "\u5019\u9009\u4e8b\u4ef6\u9700\u8981\u786e\u8ba4\u540e\u624d\u4f1a\u8fdb\u5165\u62a5\u4ef7\u6a21\u578b",
  addEvent: "\u65b0\u589e\u4e8b\u4ef6",
  editEvent: "\u7f16\u8f91\u4e8b\u4ef6",
  saveEvent: "\u4fdd\u5b58\u4e8b\u4ef6",
  cancel: "\u53d6\u6d88",
  eventName: "\u4e8b\u4ef6\u540d\u79f0",
  eventType: "\u4e8b\u4ef6\u7c7b\u578b",
  startDate: "\u5f00\u59cb\u65e5\u671f",
  endDate: "\u7ed3\u675f\u65e5\u671f",
  venue: "\u573a\u9986/\u533a\u57df",
  sourceName: "\u4fe1\u606f\u6765\u6e90",
  sourceUrl: "\u6765\u6e90\u94fe\u63a5",
  impactLevel: "\u5f71\u54cd\u7ea7\u522b",
  status: "\u72b6\u6001",
  notes: "\u5907\u6ce8",
  noVenue: "\u5168\u57ce/\u6682\u65e0\u5177\u4f53\u573a\u9986",
  eventCollection: "\u4e8b\u4ef6\u91c7\u96c6\u6e90",
  eventCollectionHint: "\u7c98\u8d34\u7f51\u9875\u6587\u5b57\u6216\u8f93\u5165\u94fe\u63a5\uff0c\u7cfb\u7edf\u4f1a\u8bc6\u522b\u5019\u9009\u4e8b\u4ef6",
  sourceText: "\u7f51\u9875\u6587\u5b57",
  recognizeEvents: "\u8bc6\u522b\u4e8b\u4ef6",
  fetchMgtoEvents: "\u8bfb\u53d6\u65c5\u6e38\u5c40\u6d3b\u52a8",
  importCandidates: "\u5bfc\u5165\u5019\u9009",
  candidates: "\u8bc6\u522b\u7ed3\u679c",
  noCandidates: "\u6682\u672a\u8bc6\u522b\u5230\u4e8b\u4ef6",
  dateTo: "\u81f3",
  confidenceLabel: "\u7f6e\u4fe1\u5ea6",
  baseWeight: "\u57fa\u7840\u6743\u91cd",
  confirm: "\u786e\u8ba4",
  reject: "\u62d2\u7edd",
  noEvents: "\u6ca1\u6709\u7b26\u5408\u6761\u4ef6\u7684\u4e8b\u4ef6",
  company: "\u6fb3\u95e8\u4e2d\u56fd\u65c5\u884c\u793e\u80a1\u4efd\u6709\u9650\u516c\u53f8",
  title: "\u9152\u5e97\u52a8\u6001\u5b9a\u4ef7\u5de5\u4f5c\u53f0",
  refresh: "\u5237\u65b0\u5efa\u8bae",
  close: "\u5173\u95ed",
  hotelList: "\u9152\u5e97\u5217\u8868",
  controls: "\u7b5b\u9009\u6761\u4ef6",
  roomType: "\u623f\u578b",
  predictionWindow: "\u9884\u6d4b\u7a97\u53e3",
  loading: "\u52a0\u8f7d\u4e2d",
  metrics: "\u5173\u952e\u6307\u6807",
  currentRoom: "\u5f53\u524d\u623f\u578b",
  avgRate: "\u5e73\u5747\u5efa\u8bae\u4ef7",
  uplift: "\u5efa\u8bae\u6da8\u5e45",
  chartTitle: "\u8fd1\u671f\u5efa\u8bae\u4ef7\u8d8b\u52bf",
  perNight: "MOP / \u665a",
  recommendedRate: "\u5efa\u8bae\u4ef7",
  historicalAverageRate: "\u53bb\u5e74\u540c\u65e5\u5e73\u5747\u4ef7",
  historicalComparisonDate: "\u5386\u53f2\u5bf9\u6bd4\u65e5\u671f",
  eventPremium: "\u4e8b\u4ef6\u6ea2\u4ef7",
  eventAdjustment: "\u4e8b\u4ef6\u8c03\u6574\u91d1\u989d",
  eventLogic: "\u4e8b\u4ef6\u8c03\u4ef7\u903b\u8f91",
  competitorLogic: "\u7ade\u54c1\u4ef7\u683c\u903b\u8f91",
  competitorMarketRate: "\u7ade\u54c1\u4e2d\u4f4d\u4ef7",
  competitorAdjustment: "\u7ade\u54c1\u8c03\u6574",
  noEventPremium: "\u5f53\u65e5\u65e0\u5185\u5730/\u6fb3\u95e8\u91cd\u5927\u5047\u671f\u6ea2\u4ef7",
  currentRate: "\u57fa\u7840\u623f\u4ef7",
  baseRateLogic: "\u57fa\u7840\u623f\u4ef7\u903b\u8f91",
  dayType: "\u65e5\u671f\u7c7b\u578b",
  weekday: "\u5468\u4e2d",
  weekend: "\u5468\u672b",
  rateAdvice: "\u8c03\u4ef7\u5efa\u8bae",
  confidence: "\u4fe1\u5fc3\u5ea6",
  reason: "\u5efa\u8bae\u539f\u56e0",
  roomCode: "\u623f\u578b\u4ee3\u7801",
  clickHint: "\u70b9\u51fb\u56fe\u8868\u4e0a\u7684\u65e5\u671f\u67e5\u770b\u5efa\u8bae"
};

export default function Dashboard() {
  const [activeView, setActiveView] = useState<"pricing" | "events" | "competitors">("pricing");
  const [hotels, setHotels] = useState<HotelRecord[]>([]);
  const [roomTypes, setRoomTypes] = useState<RoomType[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [selectedHotelId, setSelectedHotelId] = useState("kyoto");
  const [selectedRoomTypeId, setSelectedRoomTypeId] = useState("");
  const [selectedDays, setSelectedDays] = useState(90);
  const [selectedRecommendation, setSelectedRecommendation] =
    useState<Recommendation | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [eventStatus, setEventStatus] = useState("candidate");
  const [events, setEvents] = useState<ExternalEventRecord[]>([]);
  const [venues, setVenues] = useState<VenueRecord[]>([]);
  const [editingEvent, setEditingEvent] = useState<ExternalEventRecord | null>(null);
  const [eventForm, setEventForm] = useState<EventFormState>(() => defaultEventForm());
  const [isEventModalOpen, setIsEventModalOpen] = useState(false);
  const [isEventsLoading, setIsEventsLoading] = useState(false);
  const [collectionSourceName, setCollectionSourceName] = useState("Manual Web List");
  const [collectionSourceUrl, setCollectionSourceUrl] = useState("");
  const [collectionText, setCollectionText] = useState("");
  const [collectionCandidates, setCollectionCandidates] = useState<EventCollectionCandidate[]>([]);
  const [isCollecting, setIsCollecting] = useState(false);
  const [competitorHotels, setCompetitorHotels] = useState<CompetitorHotelRecord[]>([]);
  const [competitorRoomTypes, setCompetitorRoomTypes] = useState<CompetitorRoomTypeRecord[]>([]);
  const [competitorMappings, setCompetitorMappings] = useState<CompetitorMappingRecord[]>([]);
  const [competitorRates, setCompetitorRates] = useState<CompetitorRateObservationRecord[]>([]);
  const [selectedCompetitorHotelId, setSelectedCompetitorHotelId] = useState("");
  const [selectedCompetitorRoomTypeId, setSelectedCompetitorRoomTypeId] = useState("");
  const [newCompetitorRoomName, setNewCompetitorRoomName] = useState("");
  const [newRateDate, setNewRateDate] = useState(todayString());
  const [newRatePrice, setNewRatePrice] = useState("");
  const [isCompetitorLoading, setIsCompetitorLoading] = useState(false);

  const selectedRoomType = roomTypes.find((room) => room.id === selectedRoomTypeId);
  const activeHotel = useMemo(
    () => hotels.find((hotel) => hotel.id === selectedHotelId),
    [hotels, selectedHotelId]
  );
  const activeWindow =
    predictionWindows.find((windowOption) => windowOption.value === selectedDays) ??
    predictionWindows[predictionWindows.length - 1];
  const chartData: ChartPoint[] = recommendations.map((item) => ({
    date: item.stay_date.slice(5),
    currentRate: item.current_rate,
    recommendedRate: item.recommended_rate,
    historicalAverageRate: item.historical_average_rate,
    confidence: item.confidence,
    reason: item.reasons.join("\uff1b"),
    source: item
  }));
  const xAxisInterval = selectedDays >= 90 ? 6 : selectedDays >= 60 ? 4 : selectedDays >= 30 ? 2 : 0;
  const filteredCompetitorRoomTypes = competitorRoomTypes.filter(
    (roomType) => roomType.competitor_hotel_id === selectedCompetitorHotelId
  );
  const competitorMarketAverage = Math.round(
    competitorRates.reduce((total, rate) => total + rate.price, 0) /
      Math.max(competitorRates.length, 1)
  );

  const averageRecommendedRate = Math.round(
    recommendations.reduce((total, day) => total + day.recommended_rate, 0) /
      Math.max(recommendations.length, 1)
  );
  const averageCurrentRate = Math.round(
    recommendations.reduce((total, day) => total + day.current_rate, 0) /
      Math.max(recommendations.length, 1)
  );
  const uplift = Math.round(
    ((averageRecommendedRate - averageCurrentRate) / Math.max(averageCurrentRate, 1)) *
      100
  );

  useEffect(() => {
    fetch(`${apiBase}/hotels`)
      .then((response) => response.json())
      .then(setHotels)
      .catch(() => setHotels([]));
  }, []);

  useEffect(() => {
    fetch(`${apiBase}/room-types?hotel_id=${selectedHotelId}`)
      .then((response) => response.json())
      .then((data: RoomType[]) => {
        setRoomTypes(data);
        setSelectedRoomTypeId(data[0]?.id ?? "");
        setSelectedRecommendation(null);
      })
      .catch(() => setRoomTypes([]));
  }, [selectedHotelId]);

  useEffect(() => {
    if (selectedRoomTypeId) {
      refreshRecommendations();
    }
  }, [selectedHotelId, selectedRoomTypeId, selectedDays]);

  useEffect(() => {
    if (activeView === "events") {
      loadEvents();
      loadVenues();
    }
    if (activeView === "competitors") {
      loadCompetitorData();
    }
  }, [activeView, eventStatus, selectedRoomTypeId]);

  function refreshRecommendations() {
    setIsRefreshing(true);
    fetch(
      `${apiBase}/recommendations?hotel_id=${selectedHotelId}&room_type_id=${selectedRoomTypeId}&days=${selectedDays}`
    )
      .then((response) => response.json())
      .then((data: Recommendation[]) => {
        setRecommendations(data);
        setSelectedRecommendation(null);
      })
      .catch(() => setRecommendations([]))
      .finally(() => setIsRefreshing(false));
  }

  function loadEvents() {
    setIsEventsLoading(true);
    fetch(`${apiBase}/external-events?status=${eventStatus}`)
      .then((response) => response.json())
      .then(setEvents)
      .catch(() => setEvents([]))
      .finally(() => setIsEventsLoading(false));
  }

  function loadVenues() {
    fetch(`${apiBase}/venues`)
      .then((response) => response.json())
      .then(setVenues)
      .catch(() => setVenues([]));
  }

  function openCreateEventModal() {
    setEditingEvent(null);
    setEventForm(defaultEventForm());
    setIsEventModalOpen(true);
  }

  function openEditEventModal(event: ExternalEventRecord) {
    setEditingEvent(event);
    setEventForm({
      name: event.name,
      event_type: event.event_type,
      start_date: event.start_date,
      end_date: event.end_date,
      venue_id: event.venue_id ?? "",
      source_name: event.source_name ?? "Manual",
      source_url: event.source_url ?? "",
      confidence_score: event.confidence_score,
      impact_level: event.impact_level,
      base_weight: event.base_weight,
      status: event.status,
      notes: event.notes ?? ""
    });
    setIsEventModalOpen(true);
  }

  function updateEventForm<K extends keyof EventFormState>(key: K, value: EventFormState[K]) {
    setEventForm((current) => ({ ...current, [key]: value }));
  }

  function saveEvent() {
    const method = editingEvent ? "PUT" : "POST";
    const url = editingEvent
      ? `${apiBase}/external-events/${editingEvent.id}`
      : `${apiBase}/external-events`;
    fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...eventForm,
        venue_id: eventForm.venue_id || null,
        source_url: eventForm.source_url || null,
        notes: eventForm.notes || null
      })
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("event save failed");
        }
        setIsEventModalOpen(false);
        setEditingEvent(null);
        loadEvents();
        refreshRecommendations();
      })
      .catch(() => loadEvents());
  }

  function previewEventCollection() {
    setIsCollecting(true);
    fetch(`${apiBase}/event-collection/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_name: collectionSourceName,
        source_url: collectionSourceUrl || null,
        content: collectionText || null
      })
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("event collection preview failed");
        }
        return response.json();
      })
      .then(setCollectionCandidates)
      .catch(() => setCollectionCandidates([]))
      .finally(() => setIsCollecting(false));
  }

  function previewMgtoEvents() {
    setIsCollecting(true);
    fetch(`${apiBase}/event-collection/mgto/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ days: selectedDays, lang: "zh-hant" })
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("mgto event collection failed");
        }
        return response.json();
      })
      .then(setCollectionCandidates)
      .catch(() => setCollectionCandidates([]))
      .finally(() => setIsCollecting(false));
  }

  function importCollectionCandidates() {
    if (collectionCandidates.length === 0) {
      return;
    }
    setIsCollecting(true);
    fetch(`${apiBase}/event-collection/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidates: collectionCandidates })
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("event collection import failed");
        }
        setCollectionCandidates([]);
        setEventStatus("candidate");
        loadEvents();
      })
      .catch(() => loadEvents())
      .finally(() => setIsCollecting(false));
  }

  function loadCompetitorData() {
    setIsCompetitorLoading(true);
    Promise.all([
      fetch(`${apiBase}/competitors/hotels`).then((response) => response.json()),
      fetch(`${apiBase}/competitors/room-types`).then((response) => response.json()),
      fetch(`${apiBase}/competitors/mappings?hotel_id=${selectedHotelId}&room_type_id=${selectedRoomTypeId}`).then((response) =>
        response.json()
      ),
      fetch(`${apiBase}/competitors/rates?room_type_id=${selectedRoomTypeId}&days=${selectedDays}`).then((response) =>
        response.json()
      )
    ])
      .then(([hotelData, roomTypeData, mappingData, rateData]) => {
        setCompetitorHotels(hotelData);
        setCompetitorRoomTypes(roomTypeData);
        setCompetitorMappings(mappingData);
        setCompetitorRates(rateData);
        setSelectedCompetitorHotelId((current) => current || hotelData[0]?.id || "");
      })
      .catch(() => {
        setCompetitorHotels([]);
        setCompetitorRoomTypes([]);
        setCompetitorMappings([]);
        setCompetitorRates([]);
      })
      .finally(() => setIsCompetitorLoading(false));
  }

  function createCompetitorRoomType() {
    if (!selectedCompetitorHotelId || !newCompetitorRoomName.trim()) {
      return;
    }
    fetch(`${apiBase}/competitors/room-types`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        competitor_hotel_id: selectedCompetitorHotelId,
        name: newCompetitorRoomName.trim()
      })
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("competitor room type create failed");
        }
        setNewCompetitorRoomName("");
        loadCompetitorData();
      })
      .catch(loadCompetitorData);
  }

  function createCompetitorMapping() {
    if (!selectedRoomTypeId || !selectedCompetitorRoomTypeId) {
      return;
    }
    fetch(`${apiBase}/competitors/mappings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hotel_id: selectedHotelId,
        room_type_id: selectedRoomTypeId,
        competitor_room_type_id: Number(selectedCompetitorRoomTypeId),
        priority: 1,
        weight: 1
      })
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("competitor mapping create failed");
        }
        loadCompetitorData();
      })
      .catch(loadCompetitorData);
  }

  function deleteCompetitorMapping(mappingId: number) {
    fetch(`${apiBase}/competitors/mappings/${mappingId}`, { method: "DELETE" })
      .then(loadCompetitorData)
      .catch(loadCompetitorData);
  }

  function deleteCompetitorRoomType(roomTypeId: number) {
    fetch(`${apiBase}/competitors/room-types/${roomTypeId}`, { method: "DELETE" })
      .then(() => {
        setSelectedCompetitorRoomTypeId((current) =>
          current === String(roomTypeId) ? "" : current
        );
        loadCompetitorData();
      })
      .catch(loadCompetitorData);
  }

  function createCompetitorRate() {
    if (!selectedCompetitorRoomTypeId || !newRateDate || !newRatePrice) {
      return;
    }
    fetch(`${apiBase}/competitors/rates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        competitor_room_type_id: Number(selectedCompetitorRoomTypeId),
        stay_date: newRateDate,
        price: Number(newRatePrice),
        currency: "CNY",
        source: "manual"
      })
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("competitor rate create failed");
        }
        setNewRatePrice("");
        loadCompetitorData();
      })
      .catch(loadCompetitorData);
  }

  function updateEventStatus(eventId: number, status: string) {
    fetch(`${apiBase}/external-events/${eventId}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status })
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("event status update failed");
        }
        loadEvents();
        refreshRecommendations();
      })
      .catch(() => {
        loadEvents();
        refreshRecommendations();
      });
  }

  function showRecommendation(event: unknown) {
    const point = event as {
      activeLabel?: string;
      activePayload?: Array<{ payload?: ChartPoint }>;
    };
    const recommendation =
      point.activePayload?.[0]?.payload?.source ??
      chartData.find((item) => item.date === point.activeLabel)?.source;
    if (recommendation) {
      setSelectedRecommendation(recommendation);
    }
  }

  function renderRecommendationDot(props: unknown) {
    const { cx, cy, payload } = props as RecommendationDotProps;
    if (typeof cx !== "number" || typeof cy !== "number" || !payload?.source) {
      return <g />;
    }

    return (
      <circle
        cx={cx}
        cy={cy}
        fill="#ffffff"
        r={selectedDays > 30 ? 4 : 5}
        role="button"
        stroke="#357a68"
        strokeWidth={2}
        tabIndex={0}
        onClick={(event) => {
          event.stopPropagation();
          setSelectedRecommendation(payload.source);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setSelectedRecommendation(payload.source);
          }
        }}
      />
    );
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Hotel size={24} aria-hidden />
          <div>
            <strong>Macau CTS RMS</strong>
            <span>{copy.appSubtitle}</span>
          </div>
        </div>

        <nav className="nav" aria-label={copy.nav}>
          <button
            className={`navItem ${activeView === "pricing" ? "active" : ""}`}
            onClick={() => setActiveView("pricing")}
            type="button"
          >
            <CalendarDays size={18} aria-hidden />
            {copy.ninetyDayAdvice}
          </button>
          <button
            className={`navItem ${activeView === "events" ? "active" : ""}`}
            onClick={() => setActiveView("events")}
            type="button"
          >
            <SearchCheck size={18} aria-hidden />
            {copy.eventReview}
          </button>
          <button
            className={`navItem ${activeView === "competitors" ? "active" : ""}`}
            onClick={() => setActiveView("competitors")}
            type="button"
          >
            <Store size={18} aria-hidden />
            {copy.competitorPricing}
          </button>
        </nav>
      </aside>

      <section className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">{copy.company}</p>
            <h1>{copy.title}</h1>
          </div>
          <button
            className="iconButton"
            disabled={isRefreshing || !selectedRoomTypeId}
            onClick={refreshRecommendations}
            type="button"
            title={copy.refresh}
          >
            <RefreshCw className={isRefreshing ? "spin" : ""} size={18} aria-hidden />
          </button>
        </header>

        {activeView === "pricing" ? (
          <>
        <section className="hotelStrip" aria-label={copy.hotelList}>
          {hotels.map((hotel) => (
            <button
              className={`hotelButton ${hotel.id === selectedHotelId ? "selected" : ""}`}
              key={hotel.id}
              onClick={() => setSelectedHotelId(hotel.id)}
              type="button"
            >
              <strong>{hotel.name}</strong>
              <span>{hotel.district}</span>
            </button>
          ))}
        </section>

        <section className="controls" aria-label={copy.controls}>
          <div className="controlGroup">
            <label>
              {copy.roomType}
              <select
                value={selectedRoomTypeId}
                onChange={(event) => setSelectedRoomTypeId(event.target.value)}
              >
                {roomTypes.map((roomType) => (
                  <option key={roomType.id} value={roomType.id}>
                    {roomType.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {copy.predictionWindow}
              <select
                value={selectedDays}
                onChange={(event) => setSelectedDays(Number(event.target.value))}
              >
                {predictionWindows.map((windowOption) => (
                  <option key={windowOption.value} value={windowOption.value}>
                    {windowOption.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <span>
            {activeHotel
              ? `${activeHotel.name} / ${activeHotel.district}`
              : copy.loading}
          </span>
        </section>

        <section className="metrics" aria-label={copy.metrics}>
          <div className="metric">
            <span>{copy.currentRoom}</span>
            <strong>{selectedRoomType?.name ?? copy.loading}</strong>
          </div>
          <div className="metric">
            <span>{copy.avgRate}</span>
            <strong>MOP {averageRecommendedRate}</strong>
          </div>
          <div className="metric">
            <span>{copy.uplift}</span>
            <strong>{uplift}%</strong>
          </div>
          <div className="metric">
            <span>{copy.predictionWindow}</span>
            <strong>{activeWindow.label}</strong>
          </div>
        </section>

        <section className="analysisGrid single">
          <div className="panel chartPanel">
            <div className="panelHeader">
              <div>
                <h2>{copy.chartTitle}</h2>
                <span>{copy.clickHint}</span>
              </div>
              <span>{copy.perNight}</span>
            </div>
            <ResponsiveContainer width="100%" height={420}>
              <AreaChart data={chartData} onClick={showRecommendation}>
                <defs>
                  <linearGradient id="rateGradient" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="5%" stopColor="#357a68" stopOpacity={0.28} />
                    <stop offset="95%" stopColor="#357a68" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#d8ded8" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  interval={xAxisInterval}
                  minTickGap={18}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis tickLine={false} axisLine={false} width={48} />
                <Tooltip />
                <Area
                  activeDot={{ r: 7, cursor: "pointer" }}
                  dataKey="recommendedRate"
                  dot={renderRecommendationDot}
                  name={copy.recommendedRate}
                  stroke="#357a68"
                  fill="url(#rateGradient)"
                  strokeWidth={2}
                />
                <Line
                  activeDot={{ r: 6 }}
                  connectNulls={false}
                  dataKey="historicalAverageRate"
                  dot={{ r: selectedDays > 30 ? 2 : 3 }}
                  name={copy.historicalAverageRate}
                  stroke="#b56b42"
                  strokeDasharray="5 4"
                  strokeWidth={2}
                  type="monotone"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>
          </>
        ) : activeView === "events" ? (
          <section className="eventReview">
            <div className="panelHeader">
              <div>
                <h2>{copy.eventReview}</h2>
                <span>{copy.eventReviewHint}</span>
              </div>
              <div className="eventHeaderActions">
                <button className="actionButton" onClick={openCreateEventModal} type="button">
                  <Plus size={16} aria-hidden />
                  {copy.addEvent}
                </button>
                <button className="iconButton" onClick={loadEvents} type="button" title={copy.refresh}>
                  <RefreshCw className={isEventsLoading ? "spin" : ""} size={18} aria-hidden />
                </button>
              </div>
            </div>
            <section className="collectorPanel">
              <div className="collectorHeader">
                <div>
                  <h3>{copy.eventCollection}</h3>
                  <span>{copy.eventCollectionHint}</span>
                </div>
                <div className="eventHeaderActions">
                  <button
                    className="actionButton"
                    disabled={isCollecting}
                    onClick={previewMgtoEvents}
                    type="button"
                  >
                    <RefreshCw className={isCollecting ? "spin" : ""} size={16} aria-hidden />
                    {copy.fetchMgtoEvents}
                  </button>
                  <button
                    className="actionButton"
                    disabled={isCollecting || (!collectionText && !collectionSourceUrl)}
                    onClick={previewEventCollection}
                    type="button"
                  >
                    <SearchCheck size={16} aria-hidden />
                    {copy.recognizeEvents}
                  </button>
                  <button
                    className="actionButton confirm"
                    disabled={isCollecting || collectionCandidates.length === 0}
                    onClick={importCollectionCandidates}
                    type="button"
                  >
                    <Plus size={16} aria-hidden />
                    {copy.importCandidates}
                  </button>
                </div>
              </div>
              <div className="collectorForm">
                <label>
                  {copy.sourceName}
                  <input
                    value={collectionSourceName}
                    onChange={(event) => setCollectionSourceName(event.target.value)}
                  />
                </label>
                <label>
                  {copy.sourceUrl}
                  <input
                    value={collectionSourceUrl}
                    onChange={(event) => setCollectionSourceUrl(event.target.value)}
                  />
                </label>
                <label className="wide">
                  {copy.sourceText}
                  <textarea
                    rows={5}
                    value={collectionText}
                    onChange={(event) => setCollectionText(event.target.value)}
                  />
                </label>
              </div>
              <div className="candidateList">
                <strong>{copy.candidates}</strong>
                {collectionCandidates.map((candidate, index) => (
                  <article className="candidateCard" key={`${candidate.name}-${index}`}>
                    <div>
                      <span>{candidate.start_date} {copy.dateTo} {candidate.end_date}</span>
                      <strong>{candidate.name}</strong>
                    </div>
                    <div className="eventMeta">
                      <span>{candidate.event_type}</span>
                      <span>{candidate.venue_name ?? copy.noVenue}</span>
                      <span>{copy.confidenceLabel} {Math.round(candidate.confidence_score * 100)}%</span>
                      <span>{copy.baseWeight} {Math.round(candidate.base_weight * 1000) / 10}%</span>
                    </div>
                  </article>
                ))}
                {!isCollecting && collectionCandidates.length === 0 ? (
                  <div className="emptyState compact">{copy.noCandidates}</div>
                ) : null}
              </div>
            </section>
            <div className="eventToolbar">
              {["candidate", "confirmed", "rejected", "all"].map((status) => (
                <button
                  className={`statusButton ${eventStatus === status ? "active" : ""}`}
                  key={status}
                  onClick={() => setEventStatus(status)}
                  type="button"
                >
                  {status}
                </button>
              ))}
            </div>
            <div className="eventList">
              {events.map((event) => (
                <article className="eventCard" key={event.id}>
                  <header>
                    <div>
                      <strong>{event.name}</strong>
                      <span>
                        {event.start_date} {copy.dateTo} {event.end_date}
                        {event.venue_name ? ` / ${event.venue_name}` : ""}
                      </span>
                    </div>
                    <span className={`eventStatus ${event.status}`}>{event.status}</span>
                  </header>
                  <div className="eventMeta">
                    <span>{event.event_type}</span>
                    <span>{event.impact_level}</span>
                    <span>{copy.confidenceLabel} {Math.round(event.confidence_score * 100)}%</span>
                    <span>{copy.baseWeight} {Math.round(event.base_weight * 1000) / 10}%</span>
                  </div>
                  <div className="impactGrid">
                    {event.hotel_impacts.map((impact) => (
                      <div key={impact.hotel_id}>
                        <span>{impact.hotel_id}</span>
                        <strong>{Math.round(impact.final_weight * 1000) / 10}%</strong>
                      </div>
                    ))}
                  </div>
                  {event.notes ? <p>{event.notes}</p> : null}
                  <footer>
                    <button
                      className="actionButton"
                      onClick={() => openEditEventModal(event)}
                      type="button"
                    >
                      <Pencil size={16} aria-hidden />
                      {copy.editEvent}
                    </button>
                    <button
                      className="actionButton confirm"
                      disabled={event.status === "confirmed"}
                      onClick={() => updateEventStatus(event.id, "confirmed")}
                      type="button"
                    >
                      <Check size={16} aria-hidden />
                      {copy.confirm}
                    </button>
                    <button
                      className="actionButton reject"
                      disabled={event.status === "rejected"}
                      onClick={() => updateEventStatus(event.id, "rejected")}
                      type="button"
                    >
                      <X size={16} aria-hidden />
                      {copy.reject}
                    </button>
                  </footer>
                </article>
              ))}
              {!isEventsLoading && events.length === 0 ? (
                <div className="emptyState">{copy.noEvents}</div>
              ) : null}
            </div>
          </section>
        ) : (
          <section className="competitorWorkspace">
            <div className="panelHeader">
              <div>
                <h2>{copy.competitorPricing}</h2>
                <span>{copy.competitorHint}</span>
              </div>
              <button
                className="iconButton"
                disabled={isCompetitorLoading}
                onClick={loadCompetitorData}
                title={copy.refresh}
                type="button"
              >
                <RefreshCw className={isCompetitorLoading ? "spin" : ""} size={18} aria-hidden />
              </button>
            </div>

            <section className="controls competitorControls" aria-label={copy.controls}>
              <div className="controlGroup">
                <label>
                  {copy.hotelList}
                  <select
                    value={selectedHotelId}
                    onChange={(event) => setSelectedHotelId(event.target.value)}
                  >
                    {hotels.map((hotel) => (
                      <option key={hotel.id} value={hotel.id}>
                        {hotel.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {copy.roomType}
                  <select
                    value={selectedRoomTypeId}
                    onChange={(event) => setSelectedRoomTypeId(event.target.value)}
                  >
                    {roomTypes.map((roomType) => (
                      <option key={roomType.id} value={roomType.id}>
                        {roomType.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <span>{selectedRoomType?.name ?? copy.loading}</span>
            </section>

            <section className="competitorMetrics">
              <div className="metric">
                <span>{copy.competitorHotels}</span>
                <strong>{competitorHotels.length}</strong>
              </div>
              <div className="metric">
                <span>{copy.competitorRoomTypes}</span>
                <strong>{competitorRoomTypes.length}</strong>
              </div>
              <div className="metric">
                <span>{copy.mappings}</span>
                <strong>{competitorMappings.length}</strong>
              </div>
              <div className="metric">
                <span>{copy.avgRate}</span>
                <strong>{competitorRates.length ? `CNY ${competitorMarketAverage}` : "-"}</strong>
              </div>
            </section>

            <section className="competitorGrid">
              <div className="panel competitorPanel">
                <div className="panelHeader compact">
                  <div>
                    <h2>{copy.competitorHotels}</h2>
                    <span>Ctrip RPA PoC source list</span>
                  </div>
                </div>
                <div className="competitorHotelList">
                  {competitorHotels.map((hotel) => (
                    <button
                      className={`competitorHotelButton ${
                        selectedCompetitorHotelId === hotel.id ? "selected" : ""
                      }`}
                      key={hotel.id}
                      onClick={() => setSelectedCompetitorHotelId(hotel.id)}
                      type="button"
                    >
                      <strong>{hotel.name}</strong>
                      <span>{hotel.room_type_count} {copy.competitorRoomTypes}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="panel competitorPanel">
                <div className="panelHeader compact">
                  <div>
                    <h2>{copy.competitorRoomTypes}</h2>
                    <span>{copy.addCompetitorRoom}</span>
                  </div>
                </div>
                <div className="inlineForm">
                  <input
                    value={newCompetitorRoomName}
                    onChange={(event) => setNewCompetitorRoomName(event.target.value)}
                    placeholder={copy.competitorRoom}
                  />
                  <button className="actionButton" onClick={createCompetitorRoomType} type="button">
                    <Plus size={16} aria-hidden />
                    {copy.addCompetitorRoom}
                  </button>
                </div>
                <div className="compactList">
                  {filteredCompetitorRoomTypes.map((roomType) => (
                    <div className="compactListRow" key={roomType.id}>
                      <button
                        className={`compactListItem ${
                          selectedCompetitorRoomTypeId === String(roomType.id) ? "selected" : ""
                        }`}
                        onClick={() => setSelectedCompetitorRoomTypeId(String(roomType.id))}
                        type="button"
                      >
                        <strong>{roomType.name}</strong>
                        <span>{roomType.competitor_hotel_name}</span>
                      </button>
                      <button
                        className="iconButton danger"
                        onClick={() => deleteCompetitorRoomType(roomType.id)}
                        title="删除竞品房型"
                        type="button"
                      >
                        <Trash2 size={16} aria-hidden />
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              <div className="panel competitorPanel">
                <div className="panelHeader compact">
                  <div>
                    <h2>{copy.mappings}</h2>
                    <span>{selectedRoomType?.name ?? copy.loading}</span>
                  </div>
                  <button
                    className="actionButton"
                    disabled={!selectedCompetitorRoomTypeId}
                    onClick={createCompetitorMapping}
                    type="button"
                  >
                    <Plus size={16} aria-hidden />
                    {copy.addMapping}
                  </button>
                </div>
                <div className="mappingList">
                  {competitorMappings.map((mapping) => (
                    <article className="mappingCard" key={mapping.id}>
                      <div>
                        <strong>{mapping.competitor_hotel_name}</strong>
                        <span>{mapping.competitor_room_type_name}</span>
                      </div>
                      <button
                        className="iconButton"
                        onClick={() => deleteCompetitorMapping(mapping.id)}
                        title={copy.reject}
                        type="button"
                      >
                        <X size={16} aria-hidden />
                      </button>
                    </article>
                  ))}
                  {competitorMappings.length === 0 ? (
                    <div className="emptyState compact">{copy.noMappings}</div>
                  ) : null}
                </div>
              </div>

              <div className="panel competitorPanel">
                <div className="panelHeader compact">
                  <div>
                    <h2>{copy.rateObservations}</h2>
                    <span>{copy.addRate}</span>
                  </div>
                </div>
                <div className="inlineForm rateForm">
                  <input
                    type="date"
                    value={newRateDate}
                    onChange={(event) => setNewRateDate(event.target.value)}
                  />
                  <input
                    min="0"
                    type="number"
                    value={newRatePrice}
                    onChange={(event) => setNewRatePrice(event.target.value)}
                    placeholder={copy.price}
                  />
                  <button
                    className="actionButton"
                    disabled={!selectedCompetitorRoomTypeId}
                    onClick={createCompetitorRate}
                    type="button"
                  >
                    <Plus size={16} aria-hidden />
                    {copy.addRate}
                  </button>
                </div>
                <div className="rateObservationList">
                  {competitorRates.map((rate) => (
                    <article className="rateObservation" key={rate.id}>
                      <div>
                        <strong>{rate.competitor_hotel_name}</strong>
                        <span>{rate.competitor_room_type_name}</span>
                      </div>
                      <div>
                        <strong>{rate.stay_date}</strong>
                        <span>{rate.source}</span>
                      </div>
                      <strong>{rate.currency} {Math.round(rate.price)}</strong>
                    </article>
                  ))}
                  {competitorRates.length === 0 ? (
                    <div className="emptyState compact">{copy.noRates}</div>
                  ) : null}
                </div>
              </div>
            </section>
          </section>
        )}
      </section>

      {isEventModalOpen ? (
        <div className="modalBackdrop" role="presentation">
          <section className="eventModal" role="dialog" aria-modal="true">
            <header>
              <div>
                <span>{editingEvent ? copy.editEvent : copy.addEvent}</span>
                <h2>{eventForm.name || copy.eventName}</h2>
              </div>
              <button
                className="iconButton"
                onClick={() => setIsEventModalOpen(false)}
                type="button"
                title={copy.close}
              >
                <X size={18} aria-hidden />
              </button>
            </header>
            <div className="eventForm">
              <label className="wide">
                {copy.eventName}
                <input
                  value={eventForm.name}
                  onChange={(event) => updateEventForm("name", event.target.value)}
                />
              </label>
              <label>
                {copy.eventType}
                <select
                  value={eventForm.event_type}
                  onChange={(event) => updateEventForm("event_type", event.target.value)}
                >
                  {eventTypes.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {copy.impactLevel}
                <select
                  value={eventForm.impact_level}
                  onChange={(event) => updateEventForm("impact_level", event.target.value)}
                >
                  {impactLevels.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {copy.startDate}
                <input
                  type="date"
                  value={eventForm.start_date}
                  onChange={(event) => updateEventForm("start_date", event.target.value)}
                />
              </label>
              <label>
                {copy.endDate}
                <input
                  type="date"
                  value={eventForm.end_date}
                  onChange={(event) => updateEventForm("end_date", event.target.value)}
                />
              </label>
              <label className="wide">
                {copy.venue}
                <select
                  value={eventForm.venue_id}
                  onChange={(event) => updateEventForm("venue_id", event.target.value)}
                >
                  <option value="">{copy.noVenue}</option>
                  {venues.map((venue) => (
                    <option key={venue.id} value={venue.id}>
                      {venue.name} / {venue.district}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {copy.confidenceLabel}
                <input
                  max="1"
                  min="0"
                  step="0.05"
                  type="number"
                  value={eventForm.confidence_score}
                  onChange={(event) =>
                    updateEventForm("confidence_score", Number(event.target.value))
                  }
                />
              </label>
              <label>
                {copy.baseWeight}
                <input
                  max="0.35"
                  min="0"
                  step="0.01"
                  type="number"
                  value={eventForm.base_weight}
                  onChange={(event) => updateEventForm("base_weight", Number(event.target.value))}
                />
              </label>
              <label>
                {copy.status}
                <select
                  value={eventForm.status}
                  onChange={(event) => updateEventForm("status", event.target.value)}
                >
                  {eventStatuses.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {copy.sourceName}
                <input
                  value={eventForm.source_name}
                  onChange={(event) => updateEventForm("source_name", event.target.value)}
                />
              </label>
              <label className="wide">
                {copy.sourceUrl}
                <input
                  value={eventForm.source_url}
                  onChange={(event) => updateEventForm("source_url", event.target.value)}
                />
              </label>
              <label className="wide">
                {copy.notes}
                <textarea
                  rows={3}
                  value={eventForm.notes}
                  onChange={(event) => updateEventForm("notes", event.target.value)}
                />
              </label>
            </div>
            <footer className="formActions">
              <button
                className="actionButton"
                onClick={() => setIsEventModalOpen(false)}
                type="button"
              >
                {copy.cancel}
              </button>
              <button
                className="actionButton confirm"
                disabled={!eventForm.name || !eventForm.start_date || !eventForm.end_date}
                onClick={saveEvent}
                type="button"
              >
                <Check size={16} aria-hidden />
                {copy.saveEvent}
              </button>
            </footer>
          </section>
        </div>
      ) : null}

      {selectedRecommendation && selectedRoomType ? (
        <div className="modalBackdrop" role="presentation">
          <section className="adviceModal" role="dialog" aria-modal="true">
            <header>
              <div>
                <span>{selectedRecommendation.stay_date}</span>
                <h2>{copy.rateAdvice}</h2>
              </div>
              <button
                className="iconButton"
                onClick={() => setSelectedRecommendation(null)}
                type="button"
                title={copy.close}
              >
                <X size={18} aria-hidden />
              </button>
            </header>
            <div className="modalGrid">
              <div>
                <span>{copy.currentRate}</span>
                <strong>MOP {selectedRecommendation.current_rate}</strong>
              </div>
              <div>
                <span>{copy.recommendedRate}</span>
                <strong>MOP {selectedRecommendation.recommended_rate}</strong>
              </div>
              <div>
                <span>{copy.uplift}</span>
                <strong>{selectedRecommendation.change_percent}%</strong>
              </div>
              <div>
                <span>{copy.confidence}</span>
                <strong>{Math.round(selectedRecommendation.confidence * 100)}%</strong>
              </div>
            </div>
            <div className="modalGrid historical">
              <div>
                <span>{copy.eventPremium}</span>
                <strong>{Math.round(selectedRecommendation.event_premium_rate * 1000) / 10}%</strong>
              </div>
              <div>
                <span>{copy.eventAdjustment}</span>
                <strong>MOP {selectedRecommendation.event_adjustment_amount}</strong>
              </div>
            </div>
            <div className="modalGrid historical">
              <div>
                <span>{copy.historicalComparisonDate}</span>
                <strong>
                  {selectedRecommendation.historical_comparison_date ?? "-"}
                </strong>
              </div>
              <div>
                <span>{copy.historicalAverageRate}</span>
                <strong>
                  {selectedRecommendation.historical_average_rate
                    ? `MOP ${selectedRecommendation.historical_average_rate}`
                    : "-"}
                </strong>
              </div>
            </div>
            <div className="modalGrid historical">
              <div>
                <span>{copy.competitorMarketRate}</span>
                <strong>
                  {selectedRecommendation.competitor_market_rate
                    ? `MOP ${Math.round(selectedRecommendation.competitor_market_rate)}`
                    : "-"}
                </strong>
              </div>
              <div>
                <span>{copy.competitorAdjustment}</span>
                <strong>MOP {selectedRecommendation.competitor_adjustment_amount}</strong>
              </div>
            </div>
            <div className="modalReason">
              <span>{copy.competitorLogic}</span>
              {selectedRecommendation.competitor_logic.length > 0 ? (
                <ul>
                  {selectedRecommendation.competitor_logic.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>-</p>
              )}
            </div>
            <div className="modalReason">
              <span>{copy.eventLogic}</span>
              {selectedRecommendation.event_logic.length > 0 ? (
                <ul>
                  {selectedRecommendation.event_logic.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>{copy.noEventPremium}</p>
              )}
            </div>
            <div className="modalReason">
              <span>{copy.baseRateLogic}</span>
              <p>
                {selectedRecommendation.day_type === "weekend"
                  ? copy.weekend
                  : copy.weekday}
                {" / "}
                {selectedRecommendation.base_rate_source}
              </p>
            </div>
            <div className="modalReason">
              <span>{copy.roomCode}</span>
              <strong>{selectedRoomType.code}</strong>
            </div>
            <div className="modalReason">
              <span>{copy.reason}</span>
              <p>{selectedRecommendation.reasons.join("\uff1b")}</p>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
