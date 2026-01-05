_Related: [Abstract design principles](abstract-design-principles.md) • [Plugin authoring](PluginAuthoring.md) • [Architecture overview](../architecture/ArchitectureOverview.md)_

# 🚦 Development Roadmap

This roadmap tracks our progress through development and helps keep us focused on bite-sized work chunks that move us towards the end goal of a robust IPTV system.

## 🎯 Project Vision

**End Goal**: A robust IPTV-ready simulation of a professional broadcast television station with multi-channel 24/7 operation, realistic transitions and timing, and a viewer experience indistinguishable from real cable TV.

## 📊 Current Status: MPEG-TS Streaming System

### **Phase 1 — Core Architecture** ✅ **COMPLETED**

- [x] **Clean Architecture Implementation** - Domain entities, services, adapters pattern
- [x] **Database Schema** - Normalized schema for media files, shows, episodes, movies
- [x] **FastAPI Web Interface** - Modern web UI for content management
- [x] **CLI Interface** - Typer-based CLI for content operations
- [x] **Plex Integration** - Real Plex server integration with path mapping
- [x] **Content Management** - Asset/episode management with review system

### **Phase 2 — MPEG-TS Streaming** ✅ **COMPLETED**

- [x] **MPEG-TS Streaming Engine** - FFmpeg-based continuous streaming
- [x] **Concat Demuxer Integration** - Seamless content transitions
- [x] **Web Server** - FastAPI-based HTTP streaming server
- [x] **CLI Play Commands** - Play specific episodes as live streams
- [x] **Input Validation** - File validation and error handling
- [x] **Debug Tools** - Stream analysis and diagnostics

### **Phase 3 — Content Management System** ✅ **COMPLETED**

- [x] **Asset Management** - Complete asset lifecycle management
- [x] **Episode Resolution** - Series/season/episode resolution system
- [x] **Review System** - Quality assurance with human review queue
- [x] **Metadata Enrichment** - FFProbe integration for media analysis
- [x] **Path Mapping** - Plex path to local path translation
- [x] **Web Interface** - Complete web UI for content management

### **Phase 4 — Advanced Features** 🔄 **IN PROGRESS**

#### **4.1 Multi-Channel Support** 🔄 **IN PROGRESS**

- [ ] **Channel Management** - Multiple simultaneous channels
- [ ] **Channel Scheduling** - Automated content scheduling per channel
- [ ] **Channel Switching** - Dynamic channel content switching
- [ ] **Resource Management** - CPU and memory allocation per channel

#### **4.2 Commercial Insertion** 🔄 **PLANNED**

- [ ] **Commercial Management** - Commercial content library
- [ ] **Ad Break Detection** - Automatic ad break identification
- [ ] **Commercial Scheduling** - Automated commercial insertion
- [ ] **Brand Separation** - Prevent competing brands from airing together

#### **4.3 EPG/Guide Data** 🔄 **PLANNED**

- [ ] **XMLTV Export** - Standard EPG format support
- [ ] **Plex Live TV Integration** - Native Plex channel integration
- [ ] **Guide Data Generation** - Automatic program guide creation
- [ ] **Real-time Updates** - Guide data updates as schedules change

### **Phase 5 — Professional Features** 🔄 **FUTURE**

#### **5.1 Graphics and Overlays** 🔄 **PLANNED**

- [ ] **Station Branding** - Logo bugs and station identification
- [ ] **Lower Thirds** - Show information overlays
- [ ] **Emergency Graphics** - Alert overlays and emergency information
- [ ] **Custom Graphics** - User-defined overlay system

#### **5.2 Advanced Scheduling** 🔄 **PLANNED**

- [ ] **Schedule Blocks** - Programming templates and patterns
- [ ] **Daypart Rules** - Different programming for different times
- [ ] **Seasonal Programming** - Automatic seasonal content scheduling
- [ ] **Rotation Management** - Prevent content from repeating too frequently

#### **5.3 Analytics and Monitoring** 🔄 **PLANNED**

- [ ] **Play Log Tracking** - Records what actually aired
- [ ] **Performance Metrics** - System performance monitoring
- [ ] **Error Logging** - Comprehensive error tracking
- [ ] **Usage Analytics** - Content usage and performance analytics

## 🎯 Current Focus: Multi-Channel Support

### **Immediate Next Steps (Priority Order)**

#### **1. Channel Management System** 🚨 **HIGH PRIORITY**

**Why**: Foundation for multi-channel operation
**What**: Channel creation, management, and configuration
**Status**: Not started
**Estimated Time**: 8-10 hours

#### **2. Multi-Channel Streaming** 🚨 **HIGH PRIORITY**

**Why**: Core functionality for IPTV operation
**What**: Multiple simultaneous MPEG-TS streams
**Status**: Not started
**Estimated Time**: 12-15 hours

#### **3. Channel Scheduling** 🚨 **MEDIUM PRIORITY**

**Why**: Automated content scheduling per channel
**What**: Schedule management and content rotation
**Status**: Not started
**Estimated Time**: 15-20 hours

#### **4. Resource Management** 🚨 **MEDIUM PRIORITY**

**Why**: Efficient resource allocation for multiple channels
**What**: CPU and memory management per channel
**Status**: Not started
**Estimated Time**: 6-8 hours

### **Medium-Term Goals (Next 2-4 weeks)**

#### **Commercial Insertion System**

- Commercial content library management
- Ad break detection and insertion
- Brand separation and scheduling rules
- Commercial rotation and timing control

#### **EPG/Guide Data Generation**

- XMLTV format support
- Plex Live TV integration
- Real-time guide data updates
- Standard EPG format compatibility

#### **Advanced Graphics System**

- Station branding and logo bugs
- Lower thirds and information overlays
- Emergency graphics and alerts
- Custom overlay system

### **Long-Term Goals (Next 1-2 months)**

#### **Professional Broadcast Features**

- Advanced scheduling with daypart rules
- Seasonal programming automation
- Content rotation management
- Professional graphics and overlays

#### **Analytics and Monitoring**

- Comprehensive play log tracking
- Performance monitoring and alerting
- Usage analytics and reporting
- Error tracking and diagnostics

#### **Integration Features**

- Plex Live TV native integration
- XMLTV guide data export
- Remote control interface
- External API access

## 🏗️ Implementation Strategy

### **Why Multi-Channel First?**

1. **Core IPTV functionality** - Multiple channels are essential for IPTV
2. **Resource efficiency** - Better resource utilization across channels
3. **User experience** - More realistic TV experience
4. **Foundation for scheduling** - Enables advanced scheduling features

### **Multi-Channel Architecture**

```
Content Library → Channel Manager → Multiple FFmpeg Processes → MPEG-TS Streams → Network
       ↑              ↑                    ↑                      ↑           ↑
   Schedules      Channel State    Video Processing (per channel)  Streams   Clients
```

### **Component Dependencies**

- **Channel Management** ← Independent (can build first)
- **Multi-Channel Streaming** ← Depends on Channel Management
- **Resource Management** ← Depends on Multi-Channel Streaming
- **Scheduling System** ← Depends on Resource Management
- **Commercial Insertion** ← Depends on Scheduling System
- **EPG/Guide Data** ← Depends on Scheduling System

## 📈 Success Metrics

### **Phase 4 Completion Criteria (Multi-Channel Support)**

- [ ] Multiple simultaneous channels operational
- [ ] Channel management system complete
- [ ] Resource management working
- [ ] Basic scheduling system functional

### **Phase 5 Readiness Criteria (Professional Features)**

- [ ] Multi-channel system stable and performant
- [ ] Commercial insertion system working
- [ ] EPG/Guide data generation complete
- [ ] Graphics and overlay system functional

## 🎯 Next Work Session Focus

**Recommended Next Steps**:

1. **Implement Channel Management System** - Foundation for multi-channel operation
2. **Build Multi-Channel Streaming** - Core IPTV functionality
3. **Add Resource Management** - Efficient resource allocation

**Estimated Time**: 26-33 hours total
**Expected Outcome**: Multi-channel IPTV system with basic scheduling

## 📝 Notes

- **Current Status**: Single-channel MPEG-TS streaming working, focusing on multi-channel support
- **Key Achievement**: Complete content management system with web interface
- **Next Milestone**: Multi-channel IPTV system with scheduling
- **Risk Mitigation**: Channel management and resource allocation are critical path items
- **Strategic Focus**: Building professional IPTV system with multi-channel support

---

_This roadmap reflects the current state of RetroVue as a content management and streaming system, with a clear path toward professional IPTV operation._
