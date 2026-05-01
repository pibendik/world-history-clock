import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

const String kBaseUrl = 'http://localhost:8421';

const Color kBg = Color(0xFF0D1117);
const Color kSurface = Color(0xFF161B22);
const Color kAccent = Color(0xFF39D0C8);
const Color kAccentFuture = Color(0xFFC678DD);
const Color kAccentAntiquity = Color(0xFFE5A550);
const Color kTextPrimary = Color(0xFFE6EDF3);
const Color kTextMuted = Color(0xFF8B949E);

void main() => runApp(const YearClockApp());

class YearClockApp extends StatelessWidget {
  const YearClockApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'What Year Does It Look Like?',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: kBg,
        colorScheme: const ColorScheme.dark(
          background: kBg,
          surface: kSurface,
          primary: kAccent,
          secondary: kAccentFuture,
          onBackground: kTextPrimary,
          onSurface: kTextPrimary,
        ),
        cardTheme: const CardTheme(color: kSurface),
        chipTheme: ChipThemeData(
          backgroundColor: kSurface,
          labelStyle: const TextStyle(color: kTextPrimary, fontSize: 12),
          side: const BorderSide(color: Color(0xFF30363D)),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ),
      ),
      home: const ClockScreen(),
    );
  }
}

const Map<String, List<String>> kTopicKeywords = {
  'History':            ['war', 'battle', 'treaty', 'empire', 'king', 'queen', 'revolution', 'army', 'siege', 'dynasty'],
  'Science':            ['discovered', 'invented', 'experiment', 'theory', 'element', 'chemistry', 'physics', 'biology', 'laboratory'],
  'Music':              ['music', 'symphony', 'opera', 'composer', 'song', 'concert', 'orchestra', 'piano', 'violin'],
  'Astronomy':          ['eclipse', 'comet', 'planet', 'star', 'moon', 'solar', 'lunar', 'asteroid', 'transit', 'supernova'],
  'Art & Architecture': ['painting', 'sculpture', 'architecture', 'cathedral', 'church', 'built', 'constructed', 'artist'],
  'Literature':         ['published', 'written', 'novel', 'poem', 'book', 'author', 'play', 'literature'],
  'Math':               ['theorem', 'proof', 'equation', 'calculus', 'algebra', 'geometry', 'mathematician', 'number'],
};

class ClockScreen extends StatefulWidget {
  const ClockScreen({super.key});

  @override
  State<ClockScreen> createState() => _ClockScreenState();
}

class _ClockScreenState extends State<ClockScreen> {
  Timer? _clockTimer;
  DateTime _now = DateTime.now();
  int _lastYear = -1;
  Map<String, dynamic>? _yearData;
  bool _loading = false;
  int? _viewingYear;

  String _activeTopic = 'All';
  String? _feedback;

  @override
  void initState() {
    super.initState();
    _clockTimer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
    _tick();
  }

  @override
  void dispose() {
    _clockTimer?.cancel();
    super.dispose();
  }

  void _tick() {
    final now = DateTime.now();
    setState(() => _now = now);
    if (_viewingYear == null) {
      final year = now.hour * 100 + now.minute;
      if (year != _lastYear) {
        _lastYear = year;
        _fetchYear(year);
      }
    }
  }

  int get _displayYear => _viewingYear ?? (_now.hour * 100 + _now.minute);

  Future<void> _fetchYear(int year) async {
    setState(() => _loading = true);
    try {
      final resp = await http.get(Uri.parse('$kBaseUrl/year/$year'));
      if (resp.statusCode == 200 && mounted) {
        setState(() {
          _yearData = json.decode(resp.body) as Map<String, dynamic>;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _prefetchBuffer(int year) async {
    try {
      await http.get(Uri.parse('$kBaseUrl/year/$year/buffer?window=2'));
    } catch (_) {}
  }

  Future<void> _postReaction(String reaction) async {
    final data = _yearData;
    if (data == null) return;
    final events = _filteredEvents();
    if (events.isEmpty) return;
    final ev = events.first;
    try {
      await http.post(
        Uri.parse('$kBaseUrl/reaction'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'year': data['year'],
          'text': ev['text'] ?? '',
          'source': ev['source'],
          'reaction': reaction,
        }),
      );
      _showFeedback(reaction == 'like' ? '👍 Liked' : '👎 Disliked');
    } catch (_) {
      _showFeedback('Network error');
    }
  }

  Future<void> _postSave() async {
    final data = _yearData;
    if (data == null) return;
    final events = _filteredEvents();
    if (events.isEmpty) return;
    final ev = events.first;
    try {
      await http.post(
        Uri.parse('$kBaseUrl/saved'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'year': data['year'],
          'text': ev['text'] ?? '',
          'source': ev['source'],
        }),
      );
      _showFeedback('💾 Saved');
    } catch (_) {
      _showFeedback('Network error');
    }
  }

  void _navigateYear(int delta) {
    final next = _displayYear + delta;
    setState(() => _viewingYear = next);
    _fetchYear(next);
    _prefetchBuffer(next);
  }

  void _resetToLive() {
    setState(() {
      _viewingYear = null;
      _activeTopic = 'All';
    });
    final year = _now.hour * 100 + _now.minute;
    _lastYear = year;
    _fetchYear(year);
  }

  List<Map<String, dynamic>> _filteredEvents() {
    final raw = _yearData?['events'];
    if (raw == null) return [];
    final all = (raw as List).cast<Map<String, dynamic>>();
    if (_activeTopic == 'All') return all;
    final kws = kTopicKeywords[_activeTopic];
    if (kws == null) return all;
    final filtered = all.where((e) {
      final text = (e['text'] ?? '').toString().toLowerCase();
      return kws.any((k) => text.contains(k));
    }).toList();
    return filtered.isEmpty ? all : filtered;
  }

  Set<String> _topicsWithMatches() {
    final raw = _yearData?['events'];
    if (raw == null) return {};
    final all = (raw as List).cast<Map<String, dynamic>>();
    final matched = <String>{};
    for (final entry in kTopicKeywords.entries) {
      if (all.any((e) {
        final text = (e['text'] ?? '').toString().toLowerCase();
        return entry.value.any((k) => text.contains(k));
      })) {
        matched.add(entry.key);
      }
    }
    return matched;
  }

  void _showFeedback(String msg) {
    setState(() => _feedback = msg);
    Future.delayed(const Duration(seconds: 2), () {
      if (mounted) setState(() => _feedback = null);
    });
  }

  Color get _accentColor {
    final data = _yearData;
    if (data == null) return kAccent;
    if (data['is_future'] == true) return kAccentFuture;
    final year = (data['year'] as int?) ?? 0;
    if (year < 500) return kAccentAntiquity;
    return kAccent;
  }

  String _formatTime12(DateTime dt) {
    final hh = dt.hour % 12 == 0 ? 12 : dt.hour % 12;
    final mm = dt.minute.toString().padLeft(2, '0');
    final ss = dt.second.toString().padLeft(2, '0');
    final ampm = dt.hour < 12 ? 'AM' : 'PM';
    return '$hh:$mm:$ss $ampm';
  }

  String _formatTimeMilitary(DateTime dt) {
    final hh = dt.hour.toString().padLeft(2, '0');
    final mm = dt.minute.toString().padLeft(2, '0');
    final ss = dt.second.toString().padLeft(2, '0');
    return '$hh:$mm:$ss';
  }

  @override
  Widget build(BuildContext context) {
    final accent = _accentColor;
    final data = _yearData;
    final events = _filteredEvents();
    final matchedTopics = _topicsWithMatches();
    final isLive = _viewingYear == null;

    return Scaffold(
      backgroundColor: kBg,
      body: SafeArea(
        child: Stack(
          children: [
            CustomScrollView(
              slivers: [
                SliverToBoxAdapter(child: _buildHeader(accent, isLive)),
                SliverToBoxAdapter(child: _buildYearCard(accent, data)),
                SliverToBoxAdapter(child: _buildTopicRow(matchedTopics, accent)),
                if (_loading)
                  const SliverToBoxAdapter(
                    child: Padding(
                      padding: EdgeInsets.all(32),
                      child: Center(child: CircularProgressIndicator()),
                    ),
                  )
                else if (data != null && data['is_future'] == true)
                  SliverToBoxAdapter(child: _buildFutureCard(accent))
                else ...[
                  SliverToBoxAdapter(child: _buildActionBar(accent, events)),
                  SliverPadding(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                    sliver: SliverList(
                      delegate: SliverChildBuilderDelegate(
                        (ctx, i) => _buildEventCard(events[i], accent, i == 0),
                        childCount: events.length,
                      ),
                    ),
                  ),
                ],
                const SliverToBoxAdapter(child: SizedBox(height: 80)),
              ],
            ),
            if (_feedback != null)
              Positioned(
                bottom: 24,
                left: 0,
                right: 0,
                child: Center(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                    decoration: BoxDecoration(
                      color: kSurface,
                      borderRadius: BorderRadius.circular(24),
                      border: Border.all(color: accent.withOpacity(0.5)),
                    ),
                    child: Text(_feedback!, style: TextStyle(color: accent)),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader(Color accent, bool isLive) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _formatTime12(_now),
                  style: TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.bold,
                    color: accent,
                  ),
                ),
                Text(
                  _formatTimeMilitary(_now),
                  style: const TextStyle(fontSize: 14, color: kTextMuted),
                ),
              ],
            ),
          ),
          if (!isLive)
            TextButton.icon(
              onPressed: _resetToLive,
              icon: const Icon(Icons.access_time, size: 16),
              label: const Text('Live'),
              style: TextButton.styleFrom(foregroundColor: accent),
            ),
        ],
      ),
    );
  }

  Widget _buildYearCard(Color accent, Map<String, dynamic>? data) {
    final year = data?['year'] ?? _displayYear;
    final eraDisplay = (data?['era_display'] ?? '') as String;

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            children: [
              Text(
                year.toString(),
                style: TextStyle(
                  fontSize: 72,
                  fontWeight: FontWeight.w900,
                  color: accent,
                  height: 1.0,
                ),
              ),
              if (eraDisplay.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  eraDisplay,
                  style: const TextStyle(fontSize: 16, color: kTextMuted),
                  textAlign: TextAlign.center,
                ),
              ],
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  IconButton(
                    icon: const Icon(Icons.arrow_back_ios),
                    color: accent,
                    onPressed: () => _navigateYear(-1),
                    tooltip: 'Previous year',
                  ),
                  const SizedBox(width: 8),
                  Text(
                    _viewingYear != null ? 'Viewing year' : 'Live',
                    style: const TextStyle(color: kTextMuted, fontSize: 12),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    icon: const Icon(Icons.arrow_forward_ios),
                    color: accent,
                    onPressed: () => _navigateYear(1),
                    tooltip: 'Next year',
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildTopicRow(Set<String> matchedTopics, Color accent) {
    final topics = ['All', ...kTopicKeywords.keys];
    return SizedBox(
      height: 44,
      child: ListView.builder(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        itemCount: topics.length,
        itemBuilder: (ctx, i) {
          final topic = topics[i];
          final isActive = topic == _activeTopic;
          final hasMatch = topic == 'All' || matchedTopics.contains(topic);
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: FilterChip(
              label: Text(topic),
              selected: isActive,
              onSelected: (_) => setState(() => _activeTopic = topic),
              selectedColor: accent.withOpacity(0.2),
              checkmarkColor: accent,
              labelStyle: TextStyle(
                color: isActive ? accent : (hasMatch ? kTextPrimary : kTextMuted),
                fontSize: 12,
              ),
              side: BorderSide(color: isActive ? accent : const Color(0xFF30363D)),
              backgroundColor: kSurface,
            ),
          );
        },
      ),
    );
  }

  Widget _buildActionBar(Color accent, List<Map<String, dynamic>> events) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          Text(
            '${events.length} event${events.length != 1 ? 's' : ''}',
            style: const TextStyle(color: kTextMuted, fontSize: 13),
          ),
          const Spacer(),
          IconButton(
            icon: const Icon(Icons.thumb_up_outlined),
            color: accent,
            onPressed: () => _postReaction('like'),
            tooltip: 'Like',
          ),
          IconButton(
            icon: const Icon(Icons.thumb_down_outlined),
            color: kTextMuted,
            onPressed: () => _postReaction('dislike'),
            tooltip: 'Dislike',
          ),
          IconButton(
            icon: const Icon(Icons.bookmark_border),
            color: accent,
            onPressed: _postSave,
            tooltip: 'Save',
          ),
        ],
      ),
    );
  }

  Widget _buildEventCard(Map<String, dynamic> event, Color accent, bool isFirst) {
    final text = (event['text'] ?? '') as String;
    final source = event['source'] as String?;

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              text,
              style: TextStyle(
                fontSize: 14,
                color: kTextPrimary,
                fontWeight: isFirst ? FontWeight.w500 : FontWeight.normal,
              ),
            ),
            if (source != null) ...[
              const SizedBox(height: 6),
              Text(
                source,
                style: const TextStyle(fontSize: 11, color: kTextMuted),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildFutureCard(Color accent) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: [
              Icon(Icons.auto_awesome, color: accent, size: 48),
              const SizedBox(height: 12),
              Text(
                'The Future',
                style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  color: accent,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                "No historical events — this year hasn't happened yet.",
                style: TextStyle(color: kTextMuted),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
