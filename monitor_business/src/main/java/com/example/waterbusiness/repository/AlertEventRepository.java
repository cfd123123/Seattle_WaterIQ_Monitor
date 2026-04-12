package com.example.waterbusiness.repository;

import com.example.waterbusiness.entity.AlertEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.repository.query.Param;
import org.springframework.data.domain.Pageable;

import java.time.LocalDateTime;
import java.util.List;

public interface AlertEventRepository extends JpaRepository<AlertEvent, Long>, JpaSpecificationExecutor<AlertEvent> {

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    long deleteByRemark(String remark);

    List<AlertEvent> findByCreatedAtGreaterThanEqualAndCreatedAtLessThan(LocalDateTime from, LocalDateTime toExclusive);

    List<AlertEvent> findByStationIdAndCreatedAtGreaterThanEqualAndCreatedAtLessThan(
            Long stationId,
            LocalDateTime from,
            LocalDateTime toExclusive
    );

    long countByCreatedAtGreaterThanEqualAndCreatedAtLessThan(LocalDateTime from, LocalDateTime toExclusive);

    long countByStatusIn(List<String> statuses);

    long countByStationIdAndStatusIn(Long stationId, List<String> statuses);

    boolean existsByStationIdAndAlertTypeAndPollutionLevelAndStatusInAndCreatedAtGreaterThanEqual(
            Long stationId,
            String alertType,
            String pollutionLevel,
            List<String> statuses,
            LocalDateTime createdAt
    );

    boolean existsByStationIdAndAlertTypeAndStatusInAndCreatedAtGreaterThanEqual(
            Long stationId,
            String alertType,
            List<String> statuses,
            LocalDateTime createdAt
    );

    boolean existsByStationIdAndAlertTypeAndRuleCodeAndStatusInAndCreatedAtGreaterThanEqual(
            Long stationId,
            String alertType,
            String ruleCode,
            List<String> statuses,
            LocalDateTime createdAt
    );

    @Query("select e.severity, count(e) from AlertEvent e group by e.severity")
    List<Object[]> countBySeverityAll();

    @Query("""
            select e.severity, count(e)
            from AlertEvent e
            where e.createdAt >= :from and e.createdAt < :toExclusive
            group by e.severity
            """)
    List<Object[]> countBySeverityBetween(
            @Param("from") LocalDateTime from,
            @Param("toExclusive") LocalDateTime toExclusive
    );

    @Query("""
            select s.id, s.stationCode, s.stationName, count(e),
                   sum(case when e.status in ('NEW','ACK') then 1 else 0 end)
            from AlertEvent e
            join MonitorStation s on s.id = e.stationId
            where e.createdAt >= :from and e.createdAt < :toExclusive
            group by s.id, s.stationCode, s.stationName
            order by count(e) desc
            """)
    List<Object[]> topStationsByAlertCountBetween(
            @Param("from") LocalDateTime from,
            @Param("toExclusive") LocalDateTime toExclusive,
            Pageable pageable
    );
}
